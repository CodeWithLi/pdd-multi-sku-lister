"""Task queue control APIs."""

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.queue import (
    QueueCancelResponse,
    QueueControlOut,
    QueuePauseRequest,
    QueueStatusOut,
    QueueTaskOut,
)
from pdd_agent.db.repositories import (
    cancel_queued_tasks,
    get_queue_controls,
    is_queue_paused,
    list_queue_rows_for_display,
    queue_status_counts,
    set_queue_pause,
)
from pdd_agent.db.session import is_database_available
from pdd_agent.domain.enums import RunStatus
from pdd_agent.storage import TaskRunStore

router = APIRouter(prefix="/queue", tags=["queue"])


def _require_db() -> None:
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL task queue unavailable")


def _queue_task_out(row) -> QueueTaskOut:
    return QueueTaskOut(
        task_id=row.task_id,
        run_id=row.run_id,
        agent=row.agent,
        account_id=row.account_id,
        status=row.status,
        scheduled_at=row.scheduled_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        error=row.error or "",
        payload=dict(row.payload or {}),
    )


def _control_out(row) -> QueueControlOut:
    return QueueControlOut(
        scope=row.scope,
        account_id=row.account_id or "",
        paused=row.paused,
        reason=row.reason or "",
        updated_at=row.updated_at,
    )


def _get_queue_status(
    *,
    limit: int = 50,
    status: str = "",
    account_id: str = "",
) -> QueueStatusOut:
    controls = get_queue_controls()
    return QueueStatusOut(
        paused=is_queue_paused(account_id=account_id),
        counts=queue_status_counts(),
        controls=[_control_out(c) for c in controls],
        tasks=[_queue_task_out(t) for t in list_queue_rows_for_display(limit=limit, account_id=account_id)],
    )


@router.get("/status", response_model=QueueStatusOut)
def queue_status(
    limit: int = Query(default=50, ge=1, le=200),
    status: str = "",
    account_id: str = "",
):
    _require_db()
    return _get_queue_status(limit=limit, status=status, account_id=account_id)


@router.post("/pause", response_model=QueueStatusOut)
def pause_queue(body: QueuePauseRequest):
    _require_db()
    set_queue_pause(paused=True, reason=body.reason or "paused by user")
    return _get_queue_status()


@router.post("/resume", response_model=QueueStatusOut)
def resume_queue(body: QueuePauseRequest):
    _require_db()
    set_queue_pause(paused=False, reason=body.reason or "resumed by user")
    return _get_queue_status()


@router.post("/accounts/{account_id}/pause", response_model=QueueStatusOut)
def pause_account_queue(account_id: str, body: QueuePauseRequest):
    _require_db()
    set_queue_pause(paused=True, reason=body.reason or "account paused by user", account_id=account_id)
    return _get_queue_status(account_id=account_id)


@router.post("/accounts/{account_id}/resume", response_model=QueueStatusOut)
def resume_account_queue(account_id: str, body: QueuePauseRequest):
    _require_db()
    set_queue_pause(paused=False, reason=body.reason or "account resumed by user", account_id=account_id)
    return _get_queue_status(account_id=account_id)


@router.post("/cancel-queued", response_model=QueueCancelResponse)
def cancel_all_queued(account_id: str = ""):
    _require_db()
    run_ids = cancel_queued_tasks(account_id=account_id)
    store = TaskRunStore()
    for run_id in run_ids:
        store.update_status(run_id, RunStatus.CANCELED, "canceled by user")
    return QueueCancelResponse(canceled=len(run_ids), run_ids=run_ids)


@router.post("/cancel-running", response_model=QueueCancelResponse)
def cancel_all_running(account_id: str = ""):
    _require_db()
    from pdd_agent.api.app import worker

    run_ids = worker.cancel_running(account_id=account_id)
    return QueueCancelResponse(canceled=len(run_ids), run_ids=run_ids)


@router.post("/cancel-pending", response_model=QueueCancelResponse)
def cancel_all_pending(account_id: str = ""):
    """取消运行中 + 等待中的全部队列任务。"""
    _require_db()
    from pdd_agent.api.app import worker

    running_ids = worker.cancel_running(account_id=account_id)
    queued_ids = cancel_queued_tasks(account_id=account_id)
    run_ids = list(dict.fromkeys(running_ids + queued_ids))
    store = TaskRunStore()
    for run_id in run_ids:
        store.update_status(run_id, RunStatus.CANCELED, "canceled by user")
    return QueueCancelResponse(canceled=len(run_ids), run_ids=run_ids)

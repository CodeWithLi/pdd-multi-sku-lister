"""
店铺运营重置 — 同步清理 task_queue / run_records。

店铺运营状态 UI 只看 account_lifecycle + commerce_intents；
重置若只清这两张表，task_queue 里 running/queued 会残留（界面已空闲但库仍有任务）。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import cancel_queued_tasks, is_database_available
from pdd_agent.domain.enums import RunStatus
from pdd_agent.storage.task_store import TaskRunStore

logger = get_logger(__name__)


def list_accounts_with_active_queue_tasks() -> list[str]:
    """返回 task_queue 中仍有 queued/running 任务的店铺。"""
    if not is_database_available():
        return []
    from sqlalchemy import select

    from pdd_agent.db.models import TaskQueueORM
    from pdd_agent.db.session import session_scope

    with session_scope() as session:
        rows = session.scalars(
            select(TaskQueueORM.account_id)
            .where(
                TaskQueueORM.status.in_(("queued", "running")),
                TaskQueueORM.account_id != "",
            )
            .distinct()
        ).all()
    return sorted({str(aid or "").strip() for aid in rows if str(aid or "").strip()})


def cancel_account_queue_tasks(account_id: str) -> dict[str, Any]:
    """
    取消指定店铺在 task_queue 中的运行中 + 排队任务，并同步 run_records 为 canceled。
    """
    account_id = str(account_id or "").strip()
    if not account_id:
        return {"ok": False, "error": "account_id_required", "canceled_run_ids": []}

    try:
        from pdd_agent.api.app import worker
    except Exception:
        worker = None

    canceled_run_ids: list[str] = []
    if worker is not None:
        canceled_run_ids.extend(worker.cancel_running(account_id=account_id))
    else:
        from pdd_agent.db.repositories import cancel_running_tasks

        for item in cancel_running_tasks(account_id=account_id):
            rid = str(item.get("run_id") or "").strip()
            if rid:
                canceled_run_ids.append(rid)

    queued_run_ids = cancel_queued_tasks(account_id=account_id)
    canceled_run_ids = list(dict.fromkeys([*canceled_run_ids, *queued_run_ids]))

    store = TaskRunStore()
    for run_id in canceled_run_ids:
        record = store.load(run_id)
        if record and record.status in {RunStatus.PENDING, RunStatus.RUNNING}:
            store.update_status(run_id, RunStatus.CANCELED, "canceled by commerce reset")

    if canceled_run_ids:
        logger.info(
            "commerce reset canceled queue tasks account=%s run_ids=%s",
            account_id,
            canceled_run_ids,
        )
    return {
        "ok": True,
        "account_id": account_id,
        "canceled_run_ids": canceled_run_ids,
        "canceled_count": len(canceled_run_ids),
    }

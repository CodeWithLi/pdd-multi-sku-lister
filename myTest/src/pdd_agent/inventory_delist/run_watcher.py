"""库存下架 — 监听队列任务完成并推进 sequential 模式。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_queue_task_by_run_id
from pdd_agent.domain.enums import RunStatus
from pdd_agent.inventory_delist.delist_runner import (
    apply_delist_result_to_account_task,
    enqueue_account_inventory_delist,
)
from pdd_agent.inventory_delist.job_store import InventoryDelistJob, list_jobs, update_job
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)


def _terminal_statuses() -> frozenset[str]:
    return frozenset(
        {
            RunStatus.SUCCESS.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELED.value,
        }
    )


def _resolve_run_outcome(run_id: str) -> tuple[bool, dict[str, Any], str]:
    store = TaskRunStore()
    record = store.load(run_id)
    if not record:
        return False, {}, "运行记录不存在"
    status = str(record.status.value if hasattr(record.status, "value") else record.status)
    result = dict(record.result or {}) if isinstance(record.result, dict) else {}
    if status == RunStatus.SUCCESS.value:
        return True, result, ""
    if status == RunStatus.CANCELED.value:
        return False, result, "任务已取消"
    return False, result, str(record.message or "下架任务失败")


def _maybe_mark_running(account_task, run_id: str) -> None:
    queue_row = get_queue_task_by_run_id(run_id)
    if queue_row and str(queue_row.status or "").strip().lower() == "running":
        if account_task.status in {"queued", "pending"}:
            account_task.status = "running"


def _finalize_job_if_done(job: InventoryDelistJob) -> None:
    active = {"pending", "queued", "running"}
    if any(row.status in active for row in job.per_account):
        return
    failed = [row for row in job.per_account if row.status == "failed"]
    job.finished_at = datetime.now().isoformat(timespec="seconds")
    if failed:
        job.status = "failed"
        job.error = f"{len(failed)} 家店铺下架失败"
        job.message = job.error
    else:
        job.status = "completed"
        completed = sum(1 for row in job.per_account if row.status == "completed")
        skipped = sum(1 for row in job.per_account if row.status == "skipped")
        job.message = f"下架完成：{completed} 家执行，{skipped} 家跳过"
    update_job(job)


def _advance_sequential_job(
    job: InventoryDelistJob,
    *,
    delist_spec_code_search_enabled: bool,
) -> None:
    if job.execution_mode != "sequential":
        return
    if any(row.status in {"queued", "running"} for row in job.per_account):
        return
    next_task = next((row for row in job.per_account if row.status == "pending"), None)
    if not next_task:
        return
    enqueue_account_inventory_delist(
        job=job,
        account_task=next_task,
        delist_spec_code_search_enabled=delist_spec_code_search_enabled,
        dry_run=bool(job.delist_dry_run),
    )


def tick_inventory_delist_jobs(*, delist_spec_code_search_enabled: bool = False) -> int:
    """轮询活跃库存下架任务，处理完成态并推进 sequential 队列。返回处理任务数。"""
    handled = 0
    for job in list_jobs(limit=20):
        if job.status not in {"pending", "running"}:
            continue
        changed = False
        for account_task in job.per_account:
            run_id = str(account_task.run_id or "").strip()
            if not run_id or account_task.status in {"completed", "failed", "skipped"}:
                continue
            store = TaskRunStore()
            record = store.load(run_id)
            if not record:
                continue
            status = str(record.status.value if hasattr(record.status, "value") else record.status)
            if status not in _terminal_statuses():
                _maybe_mark_running(account_task, run_id)
                changed = True
                continue
            success, result, error = _resolve_run_outcome(run_id)
            apply_delist_result_to_account_task(
                account_task,
                job=job,
                success=success,
                result=result,
                error=error,
            )
            changed = True
            handled += 1
            logger.info(
                "inventory delist account finished job_id=%s account=%s run_id=%s success=%s",
                job.job_id,
                account_task.account_id,
                run_id,
                success,
            )
        if changed:
            update_job(job)
            _advance_sequential_job(job, delist_spec_code_search_enabled=delist_spec_code_search_enabled)
            _finalize_job_if_done(job)
    return handled

"""库存恢复上架 — 监听队列任务完成。"""

from __future__ import annotations

from datetime import datetime

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_queue_task_by_run_id
from pdd_agent.domain.enums import RunStatus
from pdd_agent.inventory_delist.relist_job_store import InventoryRelistJob, list_relist_jobs, update_relist_job
from pdd_agent.inventory_delist.relist_runner import (
    apply_relist_result_to_account_task,
    enqueue_account_inventory_relist,
)
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)


def _terminal_statuses() -> frozenset[str]:
    return frozenset({RunStatus.SUCCESS.value, RunStatus.FAILED.value, RunStatus.CANCELED.value})


def _resolve_run_outcome(run_id: str) -> tuple[bool, dict, str]:
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
    return False, result, str(record.message or "恢复上架任务失败")


def _finalize_job_if_done(job: InventoryRelistJob) -> None:
    active = {"pending", "queued", "running"}
    if any(row.status in active for row in job.per_account):
        return
    failed = [row for row in job.per_account if row.status == "failed"]
    job.finished_at = datetime.now().isoformat(timespec="seconds")
    if failed:
        job.status = "failed"
        job.error = f"{len(failed)} 家店铺恢复上架失败"
        job.message = job.error
    else:
        job.status = "completed"
        completed = sum(1 for row in job.per_account if row.status == "completed")
        skipped = sum(1 for row in job.per_account if row.status == "skipped")
        job.message = f"恢复上架完成：{completed} 家执行，{skipped} 家跳过"
    update_relist_job(job)


def _advance_sequential_job(job: InventoryRelistJob, *, dry_run: bool) -> None:
    if job.execution_mode != "sequential":
        return
    if any(row.status in {"queued", "running"} for row in job.per_account):
        return
    next_task = next((row for row in job.per_account if row.status == "pending"), None)
    if not next_task:
        return
    enqueue_account_inventory_relist(job=job, account_task=next_task, dry_run=dry_run)


def tick_inventory_relist_jobs() -> int:
    updated = 0
    for job in list_relist_jobs(limit=20):
        if job.status not in {"pending", "running"}:
            continue
        changed = False
        for account_task in job.per_account:
            if account_task.status not in {"queued", "running"}:
                continue
            run_id = str(account_task.run_id or "").strip()
            if not run_id:
                continue
            queue_row = get_queue_task_by_run_id(run_id)
            if queue_row and str(queue_row.status or "").strip().lower() == "running":
                if account_task.status == "queued":
                    account_task.status = "running"
                    changed = True
                continue
            store = TaskRunStore()
            record = store.load(run_id)
            if not record:
                continue
            status = str(record.status.value if hasattr(record.status, "value") else record.status)
            if status not in _terminal_statuses():
                continue
            ok, result, err = _resolve_run_outcome(run_id)
            apply_relist_result_to_account_task(
                account_task,
                job=job,
                success=ok,
                result=result,
                error=err,
            )
            changed = True
            updated += 1
        if changed:
            update_relist_job(job)
        _advance_sequential_job(job, dry_run=bool(job.relist_dry_run))
        _finalize_job_if_done(job)
    return updated

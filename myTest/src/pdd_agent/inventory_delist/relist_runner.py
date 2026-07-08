"""库存恢复上架 — 入队浏览器任务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.api.services.task_queue import enqueue_task
from pdd_agent.api.services.task_runner import create_delist_run
from pdd_agent.core.logging import get_logger
from pdd_agent.domain.enums import AgentKind
from pdd_agent.inventory_delist.relist_job_store import AccountRelistTask, InventoryRelistJob, update_relist_job

logger = get_logger(__name__)


def build_relist_targets_for_account(account_task: AccountRelistTask) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for code in account_task.candidate_codes:
        code = str(code or "").strip()
        if not code:
            continue
        targets.append(
            {
                "product_code": code,
                "record_ids": list((account_task.code_record_ids or {}).get(code) or []),
            }
        )
    return targets


def build_relist_delist_params(account_task: AccountRelistTask, *, dry_run: bool = False) -> dict[str, Any]:
    return {
        "mode": "inventory_relist",
        "dry_run": bool(dry_run),
        "targets": build_relist_targets_for_account(account_task),
        "row_strategy": "first",
    }


def enqueue_account_inventory_relist(
    *,
    job: InventoryRelistJob,
    account_task: AccountRelistTask,
    dry_run: bool = False,
) -> str:
    account_id = str(account_task.account_id or "").strip()
    if not account_task.candidate_codes:
        account_task.status = "skipped"
        update_relist_job(job)
        return ""

    run_id = create_delist_run(account_id)
    relist_params = build_relist_delist_params(account_task, dry_run=dry_run)
    enqueue_task(
        agent=AgentKind.DELIST.value,
        run_id=run_id,
        account_id=account_id,
        payload={
            "inventory_relist_job_id": job.job_id,
            "inventory_relist_account_id": account_id,
            "dry_run": bool(dry_run),
            "delist_params": relist_params,
        },
        scheduled_at=datetime.now(),
    )
    account_task.status = "queued"
    account_task.run_id = run_id
    update_relist_job(job)
    logger.info(
        "inventory relist queued job_id=%s account=%s run_id=%s targets=%s",
        job.job_id,
        account_id,
        run_id,
        len(account_task.candidate_codes),
    )
    return run_id


def start_inventory_relist_job(job: InventoryRelistJob, *, dry_run: bool = False) -> InventoryRelistJob:
    if not job.started_at:
        job.started_at = datetime.now().isoformat(timespec="seconds")
    job.status = "running"

    pending_tasks = [row for row in job.per_account if row.status == "pending"]
    if not pending_tasks:
        job.status = "completed"
        job.finished_at = datetime.now().isoformat(timespec="seconds")
        job.message = "无可恢复上架商品，任务结束"
        update_relist_job(job)
        return job

    if job.execution_mode == "parallel":
        for task in pending_tasks:
            enqueue_account_inventory_relist(job=job, account_task=task, dry_run=dry_run)
    else:
        enqueue_account_inventory_relist(job=job, account_task=pending_tasks[0], dry_run=dry_run)
    update_relist_job(job)
    return job


def apply_relist_result_to_account_task(
    account_task: AccountRelistTask,
    *,
    job: InventoryRelistJob | None = None,
    success: bool,
    result: dict[str, Any] | None,
    error: str = "",
) -> None:
    result = result if isinstance(result, dict) else {}
    if not success:
        account_task.status = "failed"
        account_task.error = str(error or "恢复上架任务失败").strip()
        if job:
            from pdd_agent.inventory_delist.relist_audit import record_account_inventory_relist_safe

            record_account_inventory_relist_safe(job, account_task, success=False, result=result, error=account_task.error)
        return

    warnings = [str(w) for w in (result.get("warnings") or []) if str(w).strip()]
    account_task.warnings = list(dict.fromkeys(warnings))
    account_task.status = "completed"

    if job:
        from pdd_agent.inventory_delist.relist_audit import record_account_inventory_relist_safe

        record_account_inventory_relist_safe(job, account_task, success=True, result=result, error="")

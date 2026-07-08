"""库存下架 — 入队精准下架任务（复用 pipeline_relist_prep 浏览器逻辑，不上架）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.api.services.pipeline_relist_strategy import (
    RelistPrepTarget,
    build_relist_prep_delist_params,
    finalize_relist_prep_after_delist,
)
from pdd_agent.api.services.task_queue import enqueue_task
from pdd_agent.api.services.task_runner import create_delist_run
from pdd_agent.core.logging import get_logger
from pdd_agent.domain.enums import AgentKind
from pdd_agent.inventory_delist.job_store import AccountDelistTask, InventoryDelistJob, update_job
from pdd_agent.inventory_delist.published_query import list_on_sale_items

logger = get_logger(__name__)


def _build_targets(account_id: str, product_codes: list[str]) -> list[RelistPrepTarget]:
    code_set = {str(code).strip() for code in product_codes if str(code).strip()}
    if not code_set:
        return []
    items = list_on_sale_items(account_id, product_codes=code_set)
    seen_merchant: set[str] = set()
    targets: list[RelistPrepTarget] = []
    for item in items:
        merchant_key = item.merchant_code.casefold()
        if merchant_key in seen_merchant:
            continue
        seen_merchant.add(merchant_key)
        targets.append(
            RelistPrepTarget(
                selector=item.selector,
                mapping_id=item.mapping_id,
                pdd_product_id=item.pdd_product_id,
                merchant_code=item.merchant_code,
            )
        )
    return targets


def enqueue_account_inventory_delist(
    *,
    job: InventoryDelistJob,
    account_task: AccountDelistTask,
    delist_spec_code_search_enabled: bool,
    dry_run: bool = False,
) -> str:
    """为单店铺入队下架任务，返回 run_id；无候选时返回空字符串。"""
    account_id = str(account_task.account_id or "").strip()
    codes = list(account_task.candidate_codes or [])
    if not codes:
        account_task.status = "skipped"
        update_job(job)
        return ""

    targets = _build_targets(account_id, codes)
    if not targets:
        account_task.status = "skipped"
        account_task.error = "未找到可下架的在售已发布记录"
        update_job(job)
        from pdd_agent.inventory_delist.audit import record_account_inventory_delist_safe

        record_account_inventory_delist_safe(
            job,
            account_task,
            success=False,
            result={},
            error=account_task.error,
        )
        return ""

    run_id = create_delist_run(account_id)
    delist_params = build_relist_prep_delist_params(
        targets,
        delist_spec_code_search_enabled=bool(delist_spec_code_search_enabled),
    )
    delist_params["inventory_delist_only"] = True

    enqueue_task(
        agent=AgentKind.DELIST.value,
        run_id=run_id,
        account_id=account_id,
        payload={
            "inventory_delist_job_id": job.job_id,
            "inventory_delist_account_id": account_id,
            "dry_run": bool(dry_run),
            "delist_params": delist_params,
        },
        scheduled_at=datetime.now(),
    )
    account_task.status = "queued"
    account_task.run_id = run_id
    account_task.target_count = len(targets)
    update_job(job)
    logger.info(
        "inventory delist queued job_id=%s account=%s run_id=%s targets=%s",
        job.job_id,
        account_id,
        run_id,
        len(targets),
    )
    return run_id


def start_inventory_delist_job(
    job: InventoryDelistJob,
    *,
    delist_spec_code_search_enabled: bool,
    dry_run: bool = False,
) -> InventoryDelistJob:
    """按执行模式启动任务：parallel 一次入队全部；sequential 仅入队第一家待处理店铺。"""
    if not job.started_at:
        job.started_at = datetime.now().isoformat(timespec="seconds")
    job.status = "running"

    pending_tasks = [row for row in job.per_account if row.status == "pending"]
    if not pending_tasks:
        job.status = "completed"
        job.finished_at = datetime.now().isoformat(timespec="seconds")
        job.message = "无负库存下架候选，任务结束"
        update_job(job)
        return job

    if job.execution_mode == "parallel":
        for task in pending_tasks:
            enqueue_account_inventory_delist(
                job=job,
                account_task=task,
                delist_spec_code_search_enabled=delist_spec_code_search_enabled,
                dry_run=dry_run,
            )
    else:
        enqueue_account_inventory_delist(
            job=job,
            account_task=pending_tasks[0],
            delist_spec_code_search_enabled=delist_spec_code_search_enabled,
            dry_run=dry_run,
        )
    update_job(job)
    return job


def apply_delist_result_to_account_task(
    account_task: AccountDelistTask,
    *,
    job: InventoryDelistJob | None = None,
    success: bool,
    result: dict[str, Any] | None,
    error: str = "",
) -> None:
    result = result if isinstance(result, dict) else {}
    warnings: list[str] = []
    if not success:
        account_task.status = "failed"
        account_task.error = str(error or "下架任务失败").strip()
        if job:
            from pdd_agent.inventory_delist.audit import record_account_inventory_delist_safe

            record_account_inventory_delist_safe(
                job,
                account_task,
                success=False,
                result=result,
                error=account_task.error,
            )
        return

    run_warnings = [str(w) for w in (result.get("warnings") or []) if str(w).strip()]
    legacy_errors = [str(e) for e in (result.get("errors") or []) if str(e).strip()]
    warnings.extend(run_warnings)
    warnings.extend(legacy_errors)

    prefetched_items = None
    deleted: list[str] = []
    if account_task.candidate_codes:
        prefetched_items = list_on_sale_items(
            account_task.account_id,
            product_codes=set(account_task.candidate_codes),
        )

    if result.get("results"):
        deleted, relist_warnings = finalize_relist_prep_after_delist(result)
        account_task.deleted_mapping_ids = deleted
        warnings.extend(relist_warnings)

    account_task.warnings = list(dict.fromkeys(warnings))
    account_task.status = "completed"

    if job:
        from pdd_agent.inventory_delist.audit import record_account_inventory_delist_safe

        record_account_inventory_delist_safe(
            job,
            account_task,
            success=True,
            result=result,
            error="",
            deleted_mapping_ids=deleted,
            prefetched_items=prefetched_items,
        )

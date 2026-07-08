"""库存恢复上架 — 写入数据库审计记录。"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import update_inventory_delist_record_relist
from pdd_agent.integrations.feishu.pdd_delist_log_sync import schedule_pdd_delist_log_relist_update
from pdd_agent.inventory_delist.relist_job_store import AccountRelistTask, InventoryRelistJob

logger = get_logger(__name__)


def _status_map(browser_status: str, *, dry_run: bool) -> tuple[bool, str]:
    status = str(browser_status or "").strip().lower()
    if status == "relisted":
        return True, "已重新上架"
    if status == "dry_run":
        return False, "联调模拟上架（dry_run）"
    if status == "not_found":
        return False, "没有搜索到该商品"
    if status == "skipped":
        return False, str(browser_status or "跳过")
    return False, str(browser_status or "恢复上架失败")


def record_account_inventory_relist(
    job: InventoryRelistJob,
    account_task: AccountRelistTask,
    *,
    success: bool,
    result: dict[str, Any] | None,
    error: str = "",
) -> int:
    written = 0
    dry_run = bool(job.relist_dry_run)
    if not success:
        for code in account_task.candidate_codes:
            record_ids = list((account_task.code_record_ids or {}).get(code) or [])
            msg = str(error or account_task.error or "恢复上架任务失败").strip()
            for rid in record_ids:
                if update_inventory_delist_record_relist(rid, is_relisted=False, message=msg):
                    written += 1
                    schedule_pdd_delist_log_relist_update(rid)
        return written

    for item in (result or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("product_code") or "").strip()
        browser_status = str(item.get("status") or "")
        message = str(item.get("message") or "").strip()
        is_relisted, default_msg = _status_map(browser_status, dry_run=dry_run)
        if not message:
            message = default_msg
        record_ids = list(item.get("record_ids") or [])
        if not record_ids and code:
            record_ids = list((account_task.code_record_ids or {}).get(code) or [])
        for rid in record_ids:
            if update_inventory_delist_record_relist(
                rid,
                is_relisted=is_relisted and not dry_run,
                message=message,
            ):
                written += 1
                schedule_pdd_delist_log_relist_update(rid)
    if written:
        logger.info(
            "inventory relist audit recorded job_id=%s account=%s rows=%s",
            job.job_id,
            account_task.account_id,
            written,
        )
    return written


def record_account_inventory_relist_safe(
    job: InventoryRelistJob,
    account_task: AccountRelistTask,
    **kwargs: Any,
) -> int:
    try:
        return record_account_inventory_relist(job, account_task, **kwargs)
    except Exception:
        logger.exception(
            "inventory relist audit failed job_id=%s account=%s",
            job.job_id,
            account_task.account_id,
        )
        return 0

"""负库存下架 — 写入数据库审计记录。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import create_inventory_delist_record
from pdd_agent.inventory_delist.job_store import AccountDelistTask, InventoryDelistJob
from pdd_agent.inventory_delist.published_query import OnSalePublishedItem, list_on_sale_items

logger = get_logger(__name__)


def _override_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in snapshot.get("test_overrides_applied") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if code:
            mapping[code.upper()] = item
    return mapping


def _inventory_for_account(snapshot: dict[str, Any], account_id: str) -> dict[str, int]:
    for row in snapshot.get("per_account") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("account_id") or "").strip() == account_id:
            raw = row.get("inventory_by_code") or {}
            return {str(k): int(v) for k, v in raw.items() if v is not None}
    raw = snapshot.get("inventory_by_code") or {}
    return {str(k): int(v) for k, v in raw.items() if v is not None}


def _group_result_items(result: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in (result or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        for key in (
            str(item.get("merchant_code") or "").strip(),
            str(item.get("selector") or "").strip(),
        ):
            if key:
                grouped.setdefault(key.upper(), []).append(item)
    return grouped


def _resolve_delist_status(
    *,
    account_success: bool,
    account_error: str,
    dry_run: bool,
    published_item: OnSalePublishedItem | None,
    result_items: list[dict[str, Any]],
    deleted_mapping_ids: set[str],
) -> tuple[str, str]:
    if not account_success:
        return "failed", account_error or "下架任务失败"
    if not published_item:
        return "skipped", "未找到本地在售记录"
    mapping_id = published_item.mapping_id
    if not result_items:
        return "not_found", "平台未命中或未执行下架"
    if any(str(item.get("status") or "") == "delisted" for item in result_items):
        if dry_run:
            return "dry_run", "联调模拟下架（dry_run）"
        if mapping_id and mapping_id in deleted_mapping_ids:
            return "completed", "已下架并清理本地记录"
        return "completed", "平台已下架"
    first_error = next(
        (str(item.get("error") or "").strip() for item in result_items if str(item.get("error") or "").strip()),
        "",
    )
    if first_error == "product_id_not_found_on_sale":
        return "not_found", "平台在售列表未找到"
    if first_error:
        return "failed", first_error
    return "failed", "下架未成功"


def record_account_inventory_delist(
    job: InventoryDelistJob,
    account_task: AccountDelistTask,
    *,
    success: bool,
    result: dict[str, Any] | None,
    error: str = "",
    deleted_mapping_ids: list[str] | None = None,
    prefetched_items: list[OnSalePublishedItem] | None = None,
) -> int:
    """按候选商品编码写入负库存下架记录，返回写入条数。"""
    codes = [str(code).strip() for code in (account_task.candidate_codes or []) if str(code).strip()]
    if not codes:
        return 0

    snapshot = dict(job.analysis_snapshot or {})
    inventory_map = _inventory_for_account(snapshot, account_task.account_id)
    overrides = _override_map(snapshot)
    common_set = {str(code).upper() for code in (job.common_on_sale_codes or [])}
    result_groups = _group_result_items(result)
    deleted_set = set(deleted_mapping_ids or [])
    shop_name = resolve_account_display_name(account_task.account_id)
    items = prefetched_items
    if items is None:
        items = list_on_sale_items(account_task.account_id, product_codes=set(codes))
    items_by_code = {item.product_code: item for item in items}

    written = 0
    now = datetime.now()
    for code in codes:
        item = items_by_code.get(code)
        merchant = item.merchant_code if item else code
        lookup_keys = {merchant.upper(), code.upper()}
        matched_results: list[dict[str, Any]] = []
        for key in lookup_keys:
            matched_results.extend(result_groups.get(key, []))

        override = overrides.get(code.upper())
        erp_qty = inventory_map.get(code)
        if erp_qty is None and item:
            erp_qty = inventory_map.get(item.merchant_code)
        original_qty = override.get("original_qty") if override else None
        if original_qty is not None:
            try:
                original_qty = int(original_qty)
            except (TypeError, ValueError):
                original_qty = None

        delist_status, message = _resolve_delist_status(
            account_success=success,
            account_error=str(error or account_task.error or "").strip(),
            dry_run=bool(job.delist_dry_run),
            published_item=item,
            result_items=matched_results,
            deleted_mapping_ids=deleted_set,
        )

        row = create_inventory_delist_record(
            job_id=job.job_id,
            run_id=str(account_task.run_id or "").strip(),
            account_id=account_task.account_id,
            shop_display_name=shop_name,
            product_code=code,
            merchant_code=merchant,
            mapping_id=item.mapping_id if item else "",
            pdd_product_id=item.pdd_product_id if item else "",
            family_code=item.family_code if item else "",
            image_set=item.image_set if item else "",
            erp_available_qty=erp_qty,
            erp_original_qty=original_qty,
            is_test_override=bool(override),
            is_common_on_sale=code.upper() in common_set,
            trigger=str(job.trigger or "manual"),
            execution_mode=str(job.execution_mode or "parallel"),
            dry_run=bool(job.delist_dry_run),
            delist_status=delist_status,
            message=message,
            delisted_at=now,
        )
        if row:
            written += 1
    if written:
        logger.info(
            "inventory delist audit recorded job_id=%s account=%s rows=%s",
            job.job_id,
            account_task.account_id,
            written,
        )
    return written


def record_account_inventory_delist_safe(
    job: InventoryDelistJob,
    account_task: AccountDelistTask,
    **kwargs: Any,
) -> int:
    try:
        return record_account_inventory_delist(job, account_task, **kwargs)
    except Exception:
        logger.exception(
            "inventory delist audit failed job_id=%s account=%s",
            job.job_id,
            account_task.account_id,
        )
        return 0

"""库存下架 — 业务服务层。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import list_inventory_delist_records
from pdd_agent.db.session import is_database_available
from pdd_agent.inventory_delist.account_resolver import resolve_enabled_account_ids
from pdd_agent.inventory_delist.analysis import InventoryDelistAnalysis, analyze_inventory_delist_targets
from pdd_agent.inventory_delist.published_query import count_published_by_account
from pdd_agent.inventory_delist.config import (
    InventoryDelistScheduleConfig,
    load_inventory_delist_config,
    save_inventory_delist_config,
)
from pdd_agent.inventory_delist.delist_runner import start_inventory_delist_job
from pdd_agent.inventory_delist.job_store import (
    InventoryDelistJob,
    create_job,
    get_job,
    get_last_scheduled_run_at,
    list_jobs,
)

logger = get_logger(__name__)


def _resolve_account_ids(account_ids: list[str] | None) -> tuple[list[str], list[str]]:
    return resolve_enabled_account_ids(account_ids)


def analysis_to_dict(analysis: InventoryDelistAnalysis) -> dict[str, Any]:
    per_account = []
    for row in analysis.per_account:
        payload = {
            "account_id": row.account_id,
            "on_sale_codes": row.on_sale_codes,
            "exclusive_codes": row.exclusive_codes,
            "negative_inventory_codes": row.negative_inventory_codes,
            "delist_candidate_codes": row.delist_candidate_codes,
            "inventory_by_code": row.inventory_by_code,
        }
        if row.published_counts:
            payload["published_counts"] = {
                "total": row.published_counts.total_rows,
                "on_sale": row.published_counts.on_sale_rows,
                "delisted": row.published_counts.delisted_rows,
                "other": row.published_counts.other_status_rows,
            }
        per_account.append(payload)
    return {
        "account_ids": analysis.account_ids,
        "common_on_sale_codes": analysis.common_on_sale_codes,
        "all_on_sale_codes": analysis.all_on_sale_codes,
        "negative_inventory_codes": analysis.negative_inventory_codes,
        "inventory_by_code": analysis.inventory_by_code,
        "feishu_query_count": analysis.feishu_query_count,
        "feishu_called": analysis.feishu_called,
        "feishu_rows_matched": analysis.feishu_rows_matched,
        "feishu_force_refresh": analysis.feishu_force_refresh,
        "feishu_error": analysis.feishu_error,
        "database_available": analysis.database_available,
        "test_override_enabled": analysis.test_override_enabled,
        "test_overrides_applied": analysis.test_overrides_applied,
        "diagnostics": analysis.diagnostics,
        "per_account": per_account,
    }


def _analyze_with_test_options(
    account_ids: list[str],
    *,
    force_feishu_refresh: bool = True,
    test_override_enabled: bool = False,
    test_inventory_overrides: dict[str, int] | None = None,
    test_override_text: str | None = None,
) -> InventoryDelistAnalysis:
    return analyze_inventory_delist_targets(
        account_ids,
        force_feishu_refresh=force_feishu_refresh,
        test_override_enabled=test_override_enabled,
        test_inventory_overrides=test_inventory_overrides,
        test_override_text=test_override_text,
    )


def preview_inventory_delist(
    *,
    account_ids: list[str] | None = None,
    force_feishu_refresh: bool = True,
    test_override_enabled: bool = False,
    test_inventory_overrides: dict[str, int] | None = None,
    test_override_text: str | None = None,
) -> dict[str, Any]:
    resolved, rejected = _resolve_account_ids(account_ids)
    logger.info(
        "inventory delist preview requested=%s resolved=%s rejected=%s force_refresh=%s test_override=%s",
        account_ids,
        resolved,
        rejected,
        force_feishu_refresh,
        test_override_enabled,
    )
    if not resolved:
        msg = "未匹配到有效店铺"
        if rejected:
            msg += f"（以下店铺 ID 不在启用列表中：{', '.join(rejected)}）"
        raise ValueError(msg)

    analysis = _analyze_with_test_options(
        resolved,
        force_feishu_refresh=bool(force_feishu_refresh),
        test_override_enabled=test_override_enabled,
        test_inventory_overrides=test_inventory_overrides,
        test_override_text=test_override_text,
    )
    result = analysis_to_dict(analysis)
    if rejected:
        result["diagnostics"] = dict(result.get("diagnostics") or {})
        result["diagnostics"]["rejected_account_ids"] = rejected
    result["requested_account_ids"] = list(account_ids or [])
    result["resolved_account_ids"] = resolved
    return result


def trigger_inventory_delist_run(
    *,
    account_ids: list[str] | None = None,
    execution_mode: str | None = None,
    delist_spec_code_search_enabled: bool | None = None,
    trigger: str = "manual",
    test_override_enabled: bool = False,
    test_inventory_overrides: dict[str, int] | None = None,
    test_override_text: str | None = None,
    delist_dry_run: bool = False,
) -> dict[str, Any]:
    if not is_database_available():
        raise RuntimeError("数据库不可用，无法入队下架任务")

    cfg = load_inventory_delist_config()
    resolved, rejected = _resolve_account_ids(account_ids or cfg.account_ids)
    if not resolved:
        msg = "请至少选择一个有效店铺"
        if rejected:
            msg += f"（无效：{', '.join(rejected)}）"
        raise ValueError(msg)

    mode = str(execution_mode or cfg.execution_mode or "parallel").strip().lower()
    if mode not in {"parallel", "sequential"}:
        mode = "parallel"
    spec_search = (
        bool(cfg.delist_spec_code_search_enabled)
        if delist_spec_code_search_enabled is None
        else bool(delist_spec_code_search_enabled)
    )

    analysis = _analyze_with_test_options(
        resolved,
        force_feishu_refresh=True,
        test_override_enabled=test_override_enabled,
        test_inventory_overrides=test_inventory_overrides,
        test_override_text=test_override_text,
    )
    snapshot = analysis_to_dict(analysis)
    if delist_dry_run:
        snapshot["delist_dry_run"] = True
    job = create_job(
        account_ids=resolved,
        execution_mode=mode,
        analysis_snapshot=snapshot,
        trigger=trigger,
    )
    job = start_inventory_delist_job(
        job,
        delist_spec_code_search_enabled=spec_search,
        dry_run=bool(delist_dry_run),
    )
    return job_to_dict(job)


def job_to_dict(job: InventoryDelistJob) -> dict[str, Any]:
    data = asdict(job)
    data["per_account"] = [asdict(row) for row in job.per_account]
    return data


def get_schedule_status() -> dict[str, Any]:
    from pdd_agent.inventory_delist.scheduler import get_inventory_delist_scheduler

    cfg = load_inventory_delist_config()
    scheduler = get_inventory_delist_scheduler()
    return {
        "enabled": cfg.enabled,
        "interval_hours": cfg.interval_hours,
        "account_ids": list(cfg.account_ids),
        "execution_mode": cfg.execution_mode,
        "delist_spec_code_search_enabled": cfg.delist_spec_code_search_enabled,
        "scheduler_running": scheduler.is_running,
        "database_available": is_database_available(),
        "last_scheduled_run_at": get_last_scheduled_run_at(),
    }


def update_schedule(body: InventoryDelistScheduleConfig) -> dict[str, Any]:
    saved = save_inventory_delist_config(body)
    return get_schedule_status() | {
        "enabled": saved.enabled,
        "interval_hours": saved.interval_hours,
        "account_ids": list(saved.account_ids),
        "execution_mode": saved.execution_mode,
        "delist_spec_code_search_enabled": saved.delist_spec_code_search_enabled,
    }


def list_inventory_delist_jobs(*, limit: int = 20) -> list[dict[str, Any]]:
    return [job_to_dict(job) for job in list_jobs(limit=limit)]


def get_inventory_delist_job(job_id: str) -> dict[str, Any] | None:
    job = get_job(job_id)
    return job_to_dict(job) if job else None


def list_on_sale_product_codes(*, account_ids: list[str] | None = None) -> dict[str, Any]:
    """列出所选店铺本地在售商品编码（不查飞书，供测试覆盖勾选）。"""
    resolved, rejected = _resolve_account_ids(account_ids)
    if not resolved:
        msg = "未匹配到有效店铺"
        if rejected:
            msg += f"（无效：{', '.join(rejected)}）"
        raise ValueError(msg)

    from pdd_agent.inventory_delist.published_query import list_on_sale_items

    per_account: list[dict[str, Any]] = []
    all_codes: set[str] = set()
    for aid in resolved:
        items = list_on_sale_items(aid)
        if not items:
            counts = count_published_by_account(aid)
            if counts.total_rows > counts.delisted_rows:
                items = list_on_sale_items(aid, include_non_on_sale=True)
        codes = sorted({item.product_code for item in items if item.product_code}, key=lambda c: c.casefold())
        all_codes.update(codes)
        per_account.append({"account_id": aid, "on_sale_codes": codes, "count": len(codes)})

    return {
        "account_ids": resolved,
        "all_on_sale_codes": sorted(all_codes, key=lambda c: c.casefold()),
        "total": len(all_codes),
        "per_account": per_account,
    }


def _record_to_dict(row) -> dict[str, Any]:
    delisted_at = row.delisted_at.isoformat(timespec="seconds") if row.delisted_at else ""
    return {
        "record_id": row.record_id,
        "job_id": row.job_id,
        "run_id": row.run_id,
        "account_id": row.account_id,
        "shop_display_name": row.shop_display_name,
        "product_code": row.product_code,
        "merchant_code": row.merchant_code,
        "mapping_id": row.mapping_id,
        "pdd_product_id": row.pdd_product_id,
        "erp_available_qty": row.erp_available_qty,
        "erp_original_qty": row.erp_original_qty,
        "is_test_override": bool(row.is_test_override),
        "is_common_on_sale": bool(row.is_common_on_sale),
        "trigger": row.trigger,
        "execution_mode": row.execution_mode,
        "dry_run": bool(row.dry_run),
        "delist_status": row.delist_status,
        "message": row.message,
        "delisted_at": delisted_at,
    }


def list_inventory_delist_record_items(
    *,
    account_id: str | None = None,
    job_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = list_inventory_delist_records(
        account_id=account_id,
        job_id=job_id,
        limit=limit,
    )
    return [_record_to_dict(row) for row in rows]

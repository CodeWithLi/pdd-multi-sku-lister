"""商品操作服务层。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.api.services.task_queue import enqueue_delist_task
from pdd_agent.api.services.task_runner import create_delist_run
from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config, search_published_products
from pdd_agent.domain.enums import AgentKind, RunStatus, TaskPhase
from pdd_agent.inventory_delist.account_resolver import resolve_enabled_account_ids
from pdd_agent.product_operations.automation import (
    read_product_price_specs,
    update_product_group_prices,
)
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)


def list_published_product_options(*, account_id: str = "") -> list[dict[str, Any]]:
    """从系统已发布记录按商品编码聚合选择项。"""
    page = 1
    rows = []
    while True:
        batch, total = search_published_products(
            page=page,
            page_size=200,
            account_id=str(account_id or "").strip(),
        )
        rows.extend(batch)
        if len(rows) >= total or not batch:
            break
        page += 1

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(getattr(row, "status", "") or "").strip() == "delisted":
            continue
        code = str(getattr(row, "product_code", "") or "").strip()
        aid = str(getattr(row, "account_id", "") or "").strip()
        product_id = str(getattr(row, "pdd_product_id", "") or "").strip()
        if not code or not aid or not product_id:
            continue
        item = grouped.setdefault(
            code,
            {
                "product_code": code,
                "listing_label": str(getattr(row, "listing_label", "") or "").strip(),
                "account_ids": [],
                "product_ids": {},
                "record_count": 0,
            },
        )
        if aid and aid not in item["account_ids"]:
            item["account_ids"].append(aid)
        item["product_ids"].setdefault(aid, product_id)
        item["record_count"] += 1

    options = []
    for item in grouped.values():
        item["account_ids"].sort()
        item["shop_count"] = len(item["account_ids"])
        options.append(item)
    return sorted(options, key=lambda item: item["product_code"].casefold())


def enqueue_product_code_delist_all_stores(product_code: str, *, dry_run: bool = False) -> list[dict[str, str]]:
    """向全部启用店铺投递同一商品编码，由每店自行搜索对应商品 ID。"""
    account_ids, _ = resolve_enabled_account_ids(None)
    if not account_ids:
        raise ValueError("没有启用的店铺")
    store = TaskRunStore()
    rows: list[dict[str, str]] = []
    for account_id in account_ids:
        run_id = create_delist_run(account_id)
        store.update_status(run_id, RunStatus.PENDING, f"queued product-code delist: {product_code}")
        enqueue_delist_task(
            run_id=run_id,
            account_id=account_id,
            dry_run=dry_run,
            delist_params={
                "merchant_code": product_code,
                "dry_run": dry_run,
                "mode": "product_operations_code",
            },
            scheduled_at=datetime.now(),
        )
        rows.append({"account_id": account_id, "run_id": run_id, "status": RunStatus.PENDING.value})
    return rows


def create_price_operation_run(account_id: str, message: str) -> str:
    store = TaskRunStore()
    run_id = store.create_run(AgentKind.LISTING, account_id).run_id
    store.update_status(run_id, RunStatus.PENDING, message)
    return run_id


async def execute_price_preview(
    *,
    run_id: str,
    account_id: str,
    product_code: str,
    expected_product_id: str = "",
) -> dict[str, Any]:
    return await _execute_price_operation(
        run_id=run_id,
        account_id=account_id,
        product_code=product_code,
        updates=None,
        expected_product_id=expected_product_id,
    )


async def execute_price_update(
    *,
    run_id: str,
    account_id: str,
    product_code: str,
    updates: list[dict[str, Any]],
    expected_product_id: str = "",
) -> dict[str, Any]:
    return await _execute_price_operation(
        run_id=run_id,
        account_id=account_id,
        product_code=product_code,
        updates=updates,
        expected_product_id=expected_product_id,
    )


async def _execute_price_operation(
    *,
    run_id: str,
    account_id: str,
    product_code: str,
    updates: list[dict[str, Any]] | None,
    expected_product_id: str,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    account = get_account_config(settings, account_id)
    if not account or not account.enabled:
        error = f"店铺不存在或未启用: {account_id}"
        store.finish(run_id, RunStatus.FAILED, error, result={"error": error})
        return {"error": error}

    operation = "price_update" if updates is not None else "price_preview"
    store.update_status(run_id, RunStatus.RUNNING, f"{operation}: {product_code}")
    store.update_phase(run_id, TaskPhase.BROWSER)

    def _job(dp):
        if updates is None:
            return read_product_price_specs(
                dp,
                account_id,
                product_code,
                expected_product_id=expected_product_id,
            )
        return update_product_group_prices(
            dp,
            account_id,
            product_code,
            updates,
            expected_product_id=expected_product_id,
        )

    try:
        result = await run_browser_job_async(settings, account, _job)
        result = {"operation": operation, **result}
        message = str(result.get("message") or f"已读取 {result.get('sku_count', 0)} 个规格")
        store.finish(
            run_id,
            RunStatus.SUCCESS,
            message,
            result=result,
            listing_labels=[product_code],
        )
        return result
    except Exception as exc:
        logger.exception("product operation failed run_id=%s operation=%s", run_id, operation)
        result = {
            "operation": operation,
            "account_id": account_id,
            "product_code": product_code,
            "error": str(exc),
        }
        store.finish(run_id, RunStatus.FAILED, str(exc), result=result, listing_labels=[product_code])
        return result

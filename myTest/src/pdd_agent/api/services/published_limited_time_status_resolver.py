"""
已发布商品 — 限时限量购状态解析。

与 task_runner / limited_time 主流程解耦，从 campaign run 结果推导每个商品的 success/failed。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pdd_agent.domain.enums import RunStatus

LIMITED_TIME_STATUS_NONE = ""
LIMITED_TIME_STATUS_SUCCESS = "success"
LIMITED_TIME_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class PublishedLimitedTimeStatusItem:
    pdd_product_id: str
    mapping_id: str
    status: str
    error: str
    run_id: str
    completed_at: datetime


def _iter_limited_time_result_items(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    items: list[dict[str, Any]] = []
    bucket = result.get("results")
    if isinstance(bucket, list):
        items.extend(item for item in bucket if isinstance(item, dict))
    if result.get("status") is not None or result.get("step"):
        items.append(result)
    return items


def _collect_selection_missing_ids(result: dict[str, Any] | None) -> dict[str, str]:
    errors: dict[str, str] = {}
    for item in _iter_limited_time_result_items(result):
        selection = item.get("product_selection") if isinstance(item.get("product_selection"), dict) else {}
        for pid in selection.get("missing_ids") or []:
            text = str(pid or "").strip()
            if text and text not in errors:
                errors[text] = str(
                    selection.get("partial_skip_reason")
                    or selection.get("error")
                    or "限时限量购选品未找到或未勾选"
                ).strip()
        partial_scope = item.get("partial_scope") if isinstance(item.get("partial_scope"), dict) else {}
        for pid in partial_scope.get("skipped_pdd_product_ids") or []:
            text = str(pid or "").strip()
            if text and text not in errors:
                errors[text] = str(
                    partial_scope.get("partial_skip_reason") or "限时限量购选品已跳过"
                ).strip()
    return errors


def resolve_published_limited_time_statuses(
    *,
    account_id: str,
    selected_product_ids: list[str] | None,
    result: dict[str, Any] | None,
    run_status: RunStatus,
    run_id: str = "",
) -> list[PublishedLimitedTimeStatusItem]:
    """为本次限时限量购涉及的商品生成 success/failed 状态列表。"""
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        extract_limited_time_success_products,
    )
    from pdd_agent.db.repositories import get_published_products_by_pdd_product_ids
    from pdd_agent.integrations.feishu.pdd_upload_sync import extract_product_ids_for_limited_time_status

    account_id = str(account_id or "").strip()
    run_id = str(run_id or "").strip()
    completed_at = datetime.now()

    product_ids = extract_product_ids_for_limited_time_status(selected_product_ids, result)
    if not product_ids:
        return []

    success_extract = extract_limited_time_success_products(
        result,
        account_id=account_id,
        fallback_pdd_ids=product_ids,
    )
    success_ids = set(success_extract.pdd_product_ids)

    from pdd_agent.api.services.task_runner import (
        _campaign_failure_message,
        _extract_limited_time_price_filter_errors,
        _extract_per_product_activity_errors,
    )

    fallback_error = _campaign_failure_message(result, run_status)
    product_errors: dict[str, str] = {}
    product_errors.update(_collect_selection_missing_ids(result))
    product_errors.update(
        _extract_per_product_activity_errors(
            result,
            fallback_error=fallback_error,
            product_ids=product_ids,
        )
    )
    if run_status == RunStatus.SUCCESS:
        product_errors.update(_extract_limited_time_price_filter_errors(result))
    elif fallback_error:
        for pid in product_ids:
            product_errors.setdefault(pid, fallback_error)

    rows = get_published_products_by_pdd_product_ids(
        account_id=account_id,
        pdd_product_ids=product_ids,
    )
    mapping_by_pdd = {
        str(row.pdd_product_id or "").strip(): str(row.mapping_id or "").strip()
        for row in rows
        if str(row.pdd_product_id or "").strip() and str(row.mapping_id or "").strip()
    }

    items: list[PublishedLimitedTimeStatusItem] = []
    for pid in product_ids:
        mapping_id = mapping_by_pdd.get(pid, "")
        if not mapping_id:
            continue
        if pid in success_ids:
            status = LIMITED_TIME_STATUS_SUCCESS
            error = ""
        else:
            status = LIMITED_TIME_STATUS_FAILED
            error = str(product_errors.get(pid) or fallback_error or "限时限量购未成功").strip()
        items.append(
            PublishedLimitedTimeStatusItem(
                pdd_product_id=pid,
                mapping_id=mapping_id,
                status=status,
                error=error,
                run_id=run_id,
                completed_at=completed_at,
            )
        )
    return items

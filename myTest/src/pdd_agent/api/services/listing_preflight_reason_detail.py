"""预检失败原因细化。

把 `preflight_no_skus` 这类宽泛结果细分成更准确的运营文案：
- 飞书查询异常
- 飞书无商品数据
- 飞书无编码 / 无子编码
- 定价缺失或无效
"""

from __future__ import annotations

from typing import Any

from pdd_agent.domain.listing_errors import ListingErrors
from pdd_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot


def _unit_warnings(preflight: Any, listing_label: str) -> list[str]:
    units: list[Any] = []
    if isinstance(preflight, dict):
        units = list(preflight.get("units") or [])
    elif preflight is not None:
        units = list(getattr(preflight, "units", None) or [])
    target = str(listing_label or "").strip()
    for unit in units:
        label = str(
            getattr(unit, "listing_label", None)
            or (unit.get("listing_label") if isinstance(unit, dict) else "")
            or ""
        ).strip()
        if label != target:
            continue
        warnings = getattr(unit, "warnings", None) or (unit.get("warnings") if isinstance(unit, dict) else [])
        return [str(item or "").strip() for item in (warnings or []) if str(item or "").strip()]
    return []


def _merchant_from_label(listing_label: str, merchant_code: str = "") -> str:
    merchant = str(merchant_code or "").strip().upper()
    if merchant:
        return merchant
    label = str(listing_label or "").strip()
    return str(label.split("/")[0] or "").strip().upper() if label else ""


def _snapshot_reason(merchant: str) -> str:
    snapshot = get_listing_feishu_snapshot()
    source = str(getattr(snapshot, "source", "") or "").strip()
    if source == "feishu_query_failed":
        return f"{merchant}飞书查询异常，暂未取到商品数据" if merchant else "飞书查询异常，暂未取到商品数据"
    if source == "feishu_empty":
        return f"{merchant}飞书无商品数据" if merchant else "飞书无商品数据"
    if source == "feishu_table_missing":
        return f"{merchant}飞书商品表未配置" if merchant else "飞书商品表未配置"
    if source == "feishu_not_configured":
        return f"{merchant}飞书未配置" if merchant else "飞书未配置"
    return ""


def infer_preflight_no_sku_brief(
    *,
    preflight: Any,
    listing_label: str,
    merchant_code: str = "",
    fallback_message: str = "",
) -> str:
    merchant = _merchant_from_label(listing_label, merchant_code)
    warnings = _unit_warnings(preflight, listing_label)

    for text in warnings + [str(fallback_message or "").strip()]:
        if not text:
            continue
        catalog_brief = ListingErrors._catalog_warning_to_brief(text)
        if catalog_brief:
            return catalog_brief

    snapshot_reason = _snapshot_reason(merchant)
    if snapshot_reason:
        return snapshot_reason
    return f"{merchant}飞书无数据或名称未匹配" if merchant else "飞书无商品数据或名称未匹配"

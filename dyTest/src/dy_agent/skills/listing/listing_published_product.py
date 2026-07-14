"""上架成功后写入 published_products 表（飞书同步后续再接）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dy_agent.core.logging import get_logger
from dy_agent.db.repositories import upsert_published_product
from dy_agent.domain.models import ListingUnit

logger = get_logger(__name__)

_LIST_STATUS_TO_PLATFORM = {
    "售卖中": "on_sale",
    "已下架": "delisted",
    "审核中": "pending_review",
    "审核驳回": "rejected",
    "已封禁": "banned",
    "已售罄": "sold_out",
    "草稿": "draft",
}


def parse_listed_at(text: str) -> datetime | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    if "T" in raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    for fmt in (
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def normalize_platform_status(list_status: str) -> str:
    raw = str(list_status or "").strip()
    if not raw:
        return "unknown"
    return _LIST_STATUS_TO_PLATFORM.get(raw, raw)


def persist_listed_product_item(
    run_id: str,
    account_id: str,
    unit: ListingUnit,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    """单个上架成功结果写入数据库。"""
    if str(item.get("status") or "") not in {"success", "listed"}:
        return None

    dy_product_id = str(item.get("dy_product_id") or "").strip()
    if not dy_product_id:
        capture = item.get("goods_list_capture")
        if isinstance(capture, dict):
            dy_product_id = str(capture.get("dy_product_id") or "").strip()
    if not dy_product_id:
        return None

    product_code = str(item.get("product_code") or unit.product_code or "").strip()
    listing_label = str(item.get("listing_label") or unit.listing_label or "").strip()
    if not product_code or not listing_label:
        return None

    list_status = str(item.get("list_status") or "").strip()
    listed_at_text = str(item.get("listed_at") or "").strip()
    product_link = str(item.get("product_link") or "").strip()
    submit_meta = item.get("publish_submit") if isinstance(item.get("publish_submit"), dict) else {}
    capture_meta = item.get("goods_list_capture") if isinstance(item.get("goods_list_capture"), dict) else {}

    submitted_at = parse_listed_at(str(submit_meta.get("submitted_at") or ""))
    listed_at = parse_listed_at(listed_at_text) or submitted_at

    row = upsert_published_product(
        account_id=account_id,
        source_run_id=str(run_id or item.get("run_id") or "").strip(),
        product_code=product_code,
        family_code=str(item.get("family_code") or unit.family_code or "").strip(),
        image_set=str(item.get("image_set") or unit.image_set or "").strip(),
        listing_label=listing_label,
        merchant_code=str(item.get("merchant_code") or unit.merchant_code or "").strip(),
        dy_product_id=dy_product_id,
        list_status=list_status,
        platform_status=normalize_platform_status(list_status),
        product_link=product_link,
        listed_at=listed_at,
        published_at=listed_at or datetime.now(),
        capture_meta={
            "goods_list_capture": capture_meta,
            "publish_submit": submit_meta,
            "product_link_ok": bool(item.get("product_link_ok")),
            "product_link_method": str(item.get("product_link_method") or capture_meta.get("product_link_method") or ""),
        },
    )
    if row is None:
        logger.warning(
            "[%s] [%s] published_products 未写入（数据库不可用）",
            account_id,
            listing_label,
        )
        return None

    logger.info(
        "[%s] [%s] 已写入 published_products mapping_id=%s dy_product_id=%s",
        account_id,
        listing_label,
        row.mapping_id,
        dy_product_id,
    )
    return {
        "mapping_id": row.mapping_id,
        "dy_product_id": row.dy_product_id,
        "list_status": row.list_status,
        "platform_status": row.platform_status,
        "listed_at": row.listed_at.isoformat(sep=" ", timespec="seconds") if row.listed_at else "",
        "product_link": row.product_link,
    }

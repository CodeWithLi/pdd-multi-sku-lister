"""每日上架成功记录（统计当天上架商品数）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.api.services.listed_folder_service import resolve_listing_source_meta
from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.db.repositories import create_daily_listing_record


def record_daily_listing_from_item(run_id: str, account_id: str, item: dict[str, Any]) -> None:
    """上架成功后追加一条每日上架记录。"""
    if not isinstance(item, dict):
        return
    if str(item.get("status") or "") not in {"success", "listed"}:
        return
    pdd_product_id = str(item.get("pdd_product_id") or "").strip()
    product_code = str(item.get("product_code") or "").strip()
    if not account_id or not pdd_product_id or not product_code:
        return

    family_code = str(item.get("family_code") or "").strip()
    image_set = str(item.get("image_set") or "").strip()
    listing_label = str(item.get("listing_label") or "").strip()
    merchant_code = str(
        item.get("platform_listing_code") or item.get("merchant_code") or ""
    ).strip()
    title = str(item.get("title") or "").strip()

    spec_metadata = item.get("spec_metadata") if isinstance(item.get("spec_metadata"), dict) else {}
    if not family_code:
        family_code = str(spec_metadata.get("family_code") or "").strip()
    if not image_set:
        image_set = str(spec_metadata.get("image_set") or "").strip()
    if not listing_label:
        listing_label = str(spec_metadata.get("listing_label") or "").strip() or (
            f"{product_code}/{image_set}" if image_set else product_code
        )

    source_kind, pipeline_id = resolve_listing_source_meta(run_id)
    create_daily_listing_record(
        account_id=account_id,
        shop_display_name=resolve_account_display_name(account_id),
        pdd_product_id=pdd_product_id,
        product_code=product_code,
        family_code=family_code,
        image_set=image_set,
        listing_label=listing_label,
        merchant_code=merchant_code,
        title=title,
        source_run_id=run_id,
        source_kind=source_kind,
        pipeline_id=pipeline_id,
        listed_at=datetime.now(),
    )

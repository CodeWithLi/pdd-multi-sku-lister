"""Derive published product price sync status from spec_metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_synced_at(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def derive_price_sync_status(spec_metadata: dict | None) -> tuple[str, datetime | None]:
    """Return (price_sync_status, synced_at).

    Status values:
    - specs_synced: pdd_goods_lookup.pdd_skus scraped from PDD
    - local_skus: local catalog SKUs already have group_price
    - detail_opened: detail/edit page opened but no SKU rows parsed
    - list_price: list row parsed with price fields
    - searched: searched in goods list but no price parsed yet
    - none: never looked up
    """
    meta = spec_metadata if isinstance(spec_metadata, dict) else {}

    lookup = meta.get("pdd_goods_lookup")
    if isinstance(lookup, dict):
        synced_at = _parse_synced_at(lookup.get("synced_at"))
        pdd_skus = lookup.get("pdd_skus")
        if isinstance(pdd_skus, list):
            for sku in pdd_skus:
                if isinstance(sku, dict) and str(sku.get("group_price") or "").strip():
                    return "specs_synced", synced_at

        status = str(lookup.get("status") or "").strip()
        list_row = lookup.get("list_row") if isinstance(lookup.get("list_row"), dict) else {}

        if str(list_row.get("group_price") or "").strip() or str(list_row.get("activity_price") or "").strip():
            return "list_price", synced_at
        if status in {"detail_opened", "edit_opened"}:
            return status, synced_at
        if status in {"searched", "search_failed"}:
            return "searched", synced_at

    skus = meta.get("skus")
    if isinstance(skus, list):
        for sku in skus:
            if isinstance(sku, dict) and str(sku.get("group_price") or "").strip():
                return "local_skus", None

    if isinstance(lookup, dict):
        synced_at = _parse_synced_at(lookup.get("synced_at"))
        return "none", synced_at
    return "none", None

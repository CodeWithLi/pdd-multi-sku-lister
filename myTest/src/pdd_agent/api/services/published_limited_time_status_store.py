"""
已发布商品 — 限时限量购状态持久化。

写入 published_products 表字段，与 resolver / bridge 解耦。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import update_published_product_limited_time_status

logger = get_logger(__name__)


def persist_published_limited_time_status_items(items: list[Any]) -> dict[str, Any]:
    """批量更新已发布商品的限时限量购状态。"""
    updated = 0
    skipped = 0
    failures: list[dict[str, str]] = []

    for item in items or []:
        mapping_id = str(getattr(item, "mapping_id", "") or "").strip()
        if not mapping_id:
            skipped += 1
            continue
        try:
            row = update_published_product_limited_time_status(
                mapping_id,
                limited_time_status=str(getattr(item, "status", "") or "").strip(),
                limited_time_error=str(getattr(item, "error", "") or "").strip(),
                limited_time_run_id=str(getattr(item, "run_id", "") or "").strip(),
                limited_time_completed_at=getattr(item, "completed_at", None),
            )
            if row is None:
                skipped += 1
                failures.append({"mapping_id": mapping_id, "reason": "row_not_found"})
                continue
            updated += 1
        except Exception as exc:
            skipped += 1
            failures.append({"mapping_id": mapping_id, "reason": str(exc)})
            logger.exception("persist published limited time status failed mapping_id=%s", mapping_id)

    summary = {
        "updated": updated,
        "skipped": skipped,
        "failures": failures,
    }
    if updated:
        logger.info(
            "published limited time status saved updated=%s skipped=%s",
            updated,
            skipped,
        )
    return summary

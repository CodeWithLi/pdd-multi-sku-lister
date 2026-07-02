"""
整合链路上架前跳过记录（平台跳过去重 / 笔袋视图无编码）。

独立模块：删改时只需移除本文件、models 表定义，以及 task_runner 中的引用调用。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select

from pdd_agent.core.logging import get_logger
from pdd_agent.db.models import IntegratedPipelineListingSkipORM
from pdd_agent.db.session import is_database_available, session_scope
from pdd_agent.integrations.feishu.listing_feishu_platform_guard import PLATFORM_SKIP_REASON

logger = get_logger(__name__)

SkipKind = Literal["platform_skip_dedupe", "bag_view_missing"]

SKIP_KIND_PLATFORM_DEDUPE: SkipKind = "platform_skip_dedupe"
SKIP_KIND_BAG_VIEW_MISSING: SkipKind = "bag_view_missing"

_SKIP_KIND_LABELS: dict[str, str] = {
    SKIP_KIND_PLATFORM_DEDUPE: "平台跳过去重",
    SKIP_KIND_BAG_VIEW_MISSING: "笔袋视图无编码",
}


def skip_kind_label(skip_kind: str) -> str:
    kind = str(skip_kind or "").strip()
    return _SKIP_KIND_LABELS.get(kind, kind)


def _day_bounds(target: date) -> tuple[datetime, datetime]:
    start = datetime(target.year, target.month, target.day)
    end = start + timedelta(days=1)
    return start, end


def _row_to_item(row: IntegratedPipelineListingSkipORM) -> dict[str, Any]:
    kind = str(row.skip_kind or "").strip()
    return {
        "record_id": row.record_id,
        "pipeline_id": row.pipeline_id,
        "listing_run_id": row.listing_run_id or "",
        "account_id": row.account_id or "",
        "skip_kind": kind,
        "skip_kind_label": skip_kind_label(kind),
        "product_selector": row.product_selector or "",
        "merchant_code": row.merchant_code or "",
        "listing_label": row.listing_label or "",
        "message": row.message or "",
        "created_at": row.created_at,
    }


def _new_record_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def record_pipeline_listing_skips(
    *,
    pipeline_id: str,
    listing_run_id: str,
    account_id: str,
    skip_kind: SkipKind,
    items: list[dict[str, Any]],
    message: str = "",
) -> int:
    """
    写入整合链路上架前跳过明细。

    无 pipeline_id、数据库不可用或 items 为空时不写入，返回 0。
    """
    pid = str(pipeline_id or "").strip()
    if not pid or not items:
        return 0
    if not is_database_available():
        return 0

    run_id = str(listing_run_id or "").strip()
    account = str(account_id or "").strip()
    kind = str(skip_kind or "").strip()
    default_message = str(message or "").strip() or _SKIP_KIND_LABELS.get(kind, kind)

    inserted = 0
    try:
        with session_scope() as session:
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                selector = str(raw.get("selector") or raw.get("product_selector") or "").strip()
                merchant_code = str(
                    raw.get("merchant_code") or raw.get("platform_listing_code") or ""
                ).strip()
                listing_label = str(raw.get("listing_label") or selector).strip()
                if not selector and not merchant_code and not listing_label:
                    continue
                item_message = str(raw.get("message") or raw.get("error") or "").strip()
                session.add(
                    IntegratedPipelineListingSkipORM(
                        record_id=_new_record_id(),
                        pipeline_id=pid,
                        listing_run_id=run_id,
                        account_id=account,
                        skip_kind=kind,
                        product_selector=selector,
                        merchant_code=merchant_code,
                        listing_label=listing_label,
                        message=item_message or default_message,
                    )
                )
                inserted += 1
    except Exception:
        logger.exception(
            "record pipeline listing skips failed pipeline_id=%s kind=%s count=%s",
            pid,
            kind,
            len(items),
        )
        return 0
    if inserted:
        logger.info(
            "pipeline listing skips recorded pipeline_id=%s run_id=%s kind=%s count=%s",
            pid,
            run_id,
            kind,
            inserted,
        )
    return inserted


def maybe_record_platform_skip_dedupe(
    *,
    pipeline_id: str,
    listing_run_id: str,
    account_id: str,
    dedupe_skipped: list[dict[str, Any]],
) -> int:
    """平台跳过去重命中时记录（整合链路专用）。"""
    if not dedupe_skipped:
        return 0
    return record_pipeline_listing_skips(
        pipeline_id=pipeline_id,
        listing_run_id=listing_run_id,
        account_id=account_id,
        skip_kind=SKIP_KIND_PLATFORM_DEDUPE,
        items=dedupe_skipped,
        message=PLATFORM_SKIP_REASON,
    )


def maybe_record_bag_view_missing(
    *,
    pipeline_id: str,
    listing_run_id: str,
    account_id: str,
    folder_by_selector: dict[str, str],
    missing_folders: set[str] | list[str],
) -> int:
    """笔袋视图未找到商品编码时记录（整合链路专用）。"""
    missing = {str(code or "").strip() for code in missing_folders if str(code or "").strip()}
    if not missing:
        return 0
    items: list[dict[str, str]] = []
    for selector, folder in folder_by_selector.items():
        if folder not in missing:
            continue
        items.append(
            {
                "selector": selector,
                "merchant_code": folder,
                "listing_label": selector,
                "message": f"笔袋视图未找到：{folder}",
            }
        )
    return record_pipeline_listing_skips(
        pipeline_id=pipeline_id,
        listing_run_id=listing_run_id,
        account_id=account_id,
        skip_kind=SKIP_KIND_BAG_VIEW_MISSING,
        items=items,
        message=PLATFORM_SKIP_REASON,
    )


def get_pipeline_listing_skip_summary(pipeline_id: str) -> dict[str, Any]:
    """按链路汇总跳过数量与明细。"""
    pid = str(pipeline_id or "").strip()
    empty = {
        "pipeline_id": pid,
        "platform_skip_dedupe": 0,
        "bag_view_missing": 0,
        "total": 0,
        "items": [],
    }
    if not pid or not is_database_available():
        return empty

    try:
        with session_scope() as session:
            rows = session.scalars(
                select(IntegratedPipelineListingSkipORM)
                .where(IntegratedPipelineListingSkipORM.pipeline_id == pid)
                .order_by(IntegratedPipelineListingSkipORM.created_at.asc())
            ).all()
    except Exception:
        logger.exception("load pipeline listing skip summary failed pipeline_id=%s", pid)
        return empty

    platform_count = 0
    bag_count = 0
    items: list[dict[str, Any]] = []
    for row in rows:
        kind = str(row.skip_kind or "").strip()
        if kind == SKIP_KIND_PLATFORM_DEDUPE:
            platform_count += 1
        elif kind == SKIP_KIND_BAG_VIEW_MISSING:
            bag_count += 1
        items.append(
            {
                "record_id": row.record_id,
                "skip_kind": kind,
                "skip_kind_label": _SKIP_KIND_LABELS.get(kind, kind),
                "listing_run_id": row.listing_run_id,
                "account_id": row.account_id,
                "product_selector": row.product_selector,
                "merchant_code": row.merchant_code,
                "listing_label": row.listing_label,
                "message": row.message,
                "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else "",
            }
        )
    return {
        "pipeline_id": pid,
        "platform_skip_dedupe": platform_count,
        "bag_view_missing": bag_count,
        "total": platform_count + bag_count,
        "items": items,
    }


def count_pipeline_listing_skips(pipeline_id: str) -> dict[str, int]:
    """仅返回各类型跳过数量。"""
    summary = get_pipeline_listing_skip_summary(pipeline_id)
    return {
        "platform_skip_dedupe": int(summary.get("platform_skip_dedupe") or 0),
        "bag_view_missing": int(summary.get("bag_view_missing") or 0),
        "total": int(summary.get("total") or 0),
    }


def count_pipeline_listing_skips_by_kind(pipeline_id: str, skip_kind: SkipKind) -> int:
    """单类型跳过数量（SQL COUNT）。"""
    pid = str(pipeline_id or "").strip()
    kind = str(skip_kind or "").strip()
    if not pid or not kind or not is_database_available():
        return 0
    try:
        with session_scope() as session:
            value = session.scalar(
                select(func.count())
                .select_from(IntegratedPipelineListingSkipORM)
                .where(
                    IntegratedPipelineListingSkipORM.pipeline_id == pid,
                    IntegratedPipelineListingSkipORM.skip_kind == kind,
                )
            )
            return int(value or 0)
    except Exception:
        logger.exception(
            "count pipeline listing skips failed pipeline_id=%s kind=%s",
            pid,
            kind,
        )
        return 0


def list_daily_pipeline_listing_skips(
    *,
    skip_date: date | None = None,
    account_id: str = "",
    skip_kind: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """按日期查询整合链路上架前跳过明细。"""
    if not is_database_available():
        return []
    target = skip_date or datetime.now().date()
    start, end = _day_bounds(target)
    account = str(account_id or "").strip()
    kind = str(skip_kind or "").strip()
    limit = max(1, min(5000, limit))
    try:
        with session_scope() as session:
            query = select(IntegratedPipelineListingSkipORM).where(
                IntegratedPipelineListingSkipORM.created_at >= start,
                IntegratedPipelineListingSkipORM.created_at < end,
            )
            if account:
                query = query.where(IntegratedPipelineListingSkipORM.account_id == account)
            if kind:
                query = query.where(IntegratedPipelineListingSkipORM.skip_kind == kind)
            rows = session.scalars(
                query.order_by(
                    IntegratedPipelineListingSkipORM.created_at.desc(),
                    IntegratedPipelineListingSkipORM.record_id.desc(),
                ).limit(limit)
            ).all()
            return [_row_to_item(row) for row in rows]
    except Exception:
        logger.exception("list daily pipeline listing skips failed date=%s", target)
        return []


def summarize_daily_pipeline_listing_skips(
    *,
    skip_date: date | None = None,
    account_id: str = "",
) -> dict[str, Any]:
    """按日期汇总整合链路上架前跳过数量。"""
    target = skip_date or datetime.now().date()
    empty = {
        "skip_date": target,
        "total": 0,
        "platform_skip_dedupe": 0,
        "bag_view_missing": 0,
        "pipeline_count": 0,
        "by_shop": [],
    }
    if not is_database_available():
        return empty

    account = str(account_id or "").strip()
    start, end = _day_bounds(target)
    try:
        with session_scope() as session:
            query = select(IntegratedPipelineListingSkipORM).where(
                IntegratedPipelineListingSkipORM.created_at >= start,
                IntegratedPipelineListingSkipORM.created_at < end,
            )
            if account:
                query = query.where(IntegratedPipelineListingSkipORM.account_id == account)
            rows = session.scalars(query).all()
    except Exception:
        logger.exception("summarize daily pipeline listing skips failed date=%s", target)
        return empty

    platform_count = 0
    bag_count = 0
    pipeline_ids: set[str] = set()
    shop_stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        kind = str(row.skip_kind or "").strip()
        if kind == SKIP_KIND_PLATFORM_DEDUPE:
            platform_count += 1
        elif kind == SKIP_KIND_BAG_VIEW_MISSING:
            bag_count += 1
        pid = str(row.pipeline_id or "").strip()
        if pid:
            pipeline_ids.add(pid)
        aid = str(row.account_id or "").strip() or "unknown"
        bucket = shop_stats.setdefault(
            aid,
            {
                "account_id": aid,
                "total": 0,
                "platform_skip_dedupe": 0,
                "bag_view_missing": 0,
            },
        )
        bucket["total"] += 1
        if kind == SKIP_KIND_PLATFORM_DEDUPE:
            bucket["platform_skip_dedupe"] += 1
        elif kind == SKIP_KIND_BAG_VIEW_MISSING:
            bucket["bag_view_missing"] += 1

    try:
        from pdd_agent.core.account_display import resolve_account_display_name

        by_shop = []
        for aid, item in sorted(shop_stats.items(), key=lambda pair: (-pair[1]["total"], pair[0])):
            by_shop.append(
                {
                    **item,
                    "shop_display_name": resolve_account_display_name(aid) if aid != "unknown" else "",
                }
            )
    except Exception:
        by_shop = list(shop_stats.values())

    return {
        "skip_date": target,
        "total": platform_count + bag_count,
        "platform_skip_dedupe": platform_count,
        "bag_view_missing": bag_count,
        "pipeline_count": len(pipeline_ids),
        "by_shop": by_shop,
    }

"""企业微信日报：拼多多店铺发布进度（自定义统计窗口）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from pdd_agent.api.services.daily_shop_publish_stats import ShopPublishStat
from pdd_agent.integrations.wecom.daily_shop_publish_progress_bridge import (
    build_shop_publish_report_text,
    collect_shop_publish_report_stats,
)
from pdd_agent.integrations.wecom.daily_shop_publish_progress_report import ShopPublishReportStat
from pdd_agent.core.logging import get_logger
from pdd_agent.core.report_time_window import (
    REPORT_WINDOW_DESCRIPTION,
    format_report_window_iso,
    format_report_window_label,
    report_listing_window,
    today_in_tz,
)

logger = get_logger(__name__)

# 兼容旧引用
StoreListingSummary = ShopPublishStat
WINDOW_START_HOUR = 18
WINDOW_START_MINUTE = 1
WINDOW_END_HOUR = 18
WINDOW_END_MINUTE = 0


@dataclass
class StoreProgressSnapshot:
    window_start: datetime
    window_end: datetime
    shops: list[ShopPublishStat]
    text: str


def format_store_progress_lines(shops: list[ShopPublishStat]) -> str:
    report_shops = [
        item if isinstance(item, ShopPublishReportStat) else ShopPublishReportStat(
            account_id=item.account_id,
            shop_display_name=item.shop_display_name,
            published_count=item.published_count,
            limited_time_success_count=item.limited_time_success_count,
            activity_register_success_count=item.activity_register_success_count,
            promotion_success_count=item.promotion_success_count,
        )
        for item in shops
    ]
    return build_shop_publish_report_text(report_shops)


def collect_pdd_store_progress(
    *,
    reference_day: date | None = None,
    now: datetime | None = None,
) -> StoreProgressSnapshot:
    """采集拼多多店铺在日报窗口内的发布进度。"""
    start, end = report_listing_window(reference_day=reference_day, now=now)
    shops: list[ShopPublishStat] = []
    try:
        shops = collect_shop_publish_report_stats(
            reference_day=reference_day or (now or datetime.now()).date(),
            now=now,
        )
    except Exception:
        logger.exception("collect pdd store progress failed")

    return StoreProgressSnapshot(
        window_start=start,
        window_end=end,
        shops=shops,
        text=format_store_progress_lines(shops),
    )


__all__ = [
    "REPORT_WINDOW_DESCRIPTION",
    "StoreListingSummary",
    "StoreProgressSnapshot",
    "WINDOW_END_HOUR",
    "WINDOW_END_MINUTE",
    "WINDOW_START_HOUR",
    "WINDOW_START_MINUTE",
    "collect_pdd_store_progress",
    "format_report_window_iso",
    "format_report_window_label",
    "format_store_progress_lines",
    "report_listing_window",
    "today_in_tz",
]

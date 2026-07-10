"""企业微信日报：店铺发布进度统计窗口解析。"""

from __future__ import annotations

from datetime import date, datetime

from pdd_agent.core.report_time_window import (
    ReportListingWindowBounds,
    format_report_window_iso,
    parse_report_window_datetime,
    report_listing_window,
)
from pdd_agent.integrations.wecom.config import WecomConfig, load_wecom_config


def bounds_from_wecom_config(cfg: WecomConfig | None = None) -> ReportListingWindowBounds:
    config = cfg or load_wecom_config()
    return ReportListingWindowBounds(
        start_hour=int(config.daily_report_store_window_start_hour),
        start_minute=int(config.daily_report_store_window_start_minute),
        end_hour=int(config.daily_report_store_window_end_hour),
        end_minute=int(config.daily_report_store_window_end_minute),
    )


def describe_store_progress_window(cfg: WecomConfig | None = None) -> str:
    return bounds_from_wecom_config(cfg).describe()


def resolve_store_progress_window(
    *,
    reference_day: date | None = None,
    listing_window_start: str = "",
    listing_window_end: str = "",
    config: WecomConfig | None = None,
) -> tuple[datetime, datetime]:
    """优先使用自定义起止时间，否则回退到配置中的默认窗口。"""
    custom_start = parse_report_window_datetime(listing_window_start)
    custom_end = parse_report_window_datetime(listing_window_end)
    if custom_start and custom_end and custom_end >= custom_start:
        return custom_start, custom_end
    bounds = bounds_from_wecom_config(config)
    return report_listing_window(reference_day=reference_day, bounds=bounds)


def resolve_store_progress_window_iso(
    *,
    reference_day: date | None = None,
    listing_window_start: str = "",
    listing_window_end: str = "",
    config: WecomConfig | None = None,
) -> tuple[str, str, datetime, datetime]:
    start, end = resolve_store_progress_window(
        reference_day=reference_day,
        listing_window_start=listing_window_start,
        listing_window_end=listing_window_end,
        config=config,
    )
    start_text, end_text = format_report_window_iso(start, end)
    return start_text, end_text, start, end

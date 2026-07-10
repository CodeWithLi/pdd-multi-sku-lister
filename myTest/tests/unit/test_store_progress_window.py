"""店铺发布进度统计窗口单元测试。"""

from __future__ import annotations

from datetime import date, datetime

from pdd_agent.core.report_time_window import ReportListingWindowBounds, report_listing_window
from pdd_agent.integrations.wecom.config import WecomConfig
from pdd_agent.integrations.wecom.store_progress_window import (
    bounds_from_wecom_config,
    resolve_store_progress_window,
)


def test_bounds_from_wecom_config():
    cfg = WecomConfig(
        enabled=False,
        daily_report_store_window_start_hour=9,
        daily_report_store_window_start_minute=30,
        daily_report_store_window_end_hour=21,
        daily_report_store_window_end_minute=15,
    )
    bounds = bounds_from_wecom_config(cfg)
    assert bounds.start_hour == 9
    assert bounds.end_minute == 15


def test_resolve_store_progress_window_prefers_custom_range():
    start, end = resolve_store_progress_window(
        listing_window_start="2026-07-01 08:00",
        listing_window_end="2026-07-10 20:00",
    )
    assert start == datetime(2026, 7, 1, 8, 0)
    assert end == datetime(2026, 7, 10, 20, 0)


def test_report_listing_window_uses_custom_bounds():
    start, end = report_listing_window(
        reference_day=date(2026, 7, 10),
        bounds=ReportListingWindowBounds(
            start_hour=9,
            start_minute=0,
            end_hour=17,
            end_minute=30,
        ),
    )
    assert start == datetime(2026, 7, 9, 9, 0)
    assert end == datetime(2026, 7, 10, 17, 30)

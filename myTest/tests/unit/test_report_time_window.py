"""日报统计窗口单元测试。"""

from __future__ import annotations

from datetime import date, datetime

from pdd_agent.core.report_time_window import (
    format_report_window_iso,
    format_report_window_label,
    report_listing_window,
)


def test_report_listing_window():
    start, end = report_listing_window(reference_day=date(2026, 7, 6))
    assert start == datetime(2026, 7, 5, 18, 1, 0)
    assert end == datetime(2026, 7, 6, 18, 0, 0)


def test_format_report_window_label():
    start = datetime(2026, 7, 5, 18, 1, 0)
    end = datetime(2026, 7, 6, 18, 0, 0)
    assert format_report_window_label(start, end) == "07-05 18:01 ~ 07-06 18:00"
    assert format_report_window_iso(start, end) == (
        "2026-07-05 18:01",
        "2026-07-06 18:00",
    )

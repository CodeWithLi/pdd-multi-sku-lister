"""企业微信日报店铺发布进度单元测试。"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

from pdd_agent.integrations.wecom.store_progress import (
    collect_pdd_store_progress,
    format_store_progress_lines,
    report_listing_window,
    StoreListingSummary,
)


def test_report_listing_window():
    start, end = report_listing_window(reference_day=date(2026, 7, 6))
    assert start == datetime(2026, 7, 5, 18, 1, 0)
    assert end == datetime(2026, 7, 6, 17, 0, 0)


def test_format_store_progress_lines():
    text = format_store_progress_lines(
        [
            StoreListingSummary(
                account_id="store_A",
                shop_display_name="兔兔潮玩屋",
                count=16,
            ),
            StoreListingSummary(
                account_id="store_B",
                shop_display_name="可可爱爱巴布豆店铺",
                count=12,
            ),
        ]
    )
    assert text == "兔兔潮玩屋：已发布16个\n可可爱爱巴布豆店铺：已发布12个"


def test_format_store_progress_skips_zero():
    text = format_store_progress_lines(
        [
            StoreListingSummary(account_id="a", shop_display_name="A店", count=0),
            StoreListingSummary(account_id="b", shop_display_name="B店", count=3),
        ]
    )
    assert text == "B店：已发布3个"


def test_collect_pdd_store_progress(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.wecom.store_progress.is_database_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.wecom.store_progress.summarize_daily_listing_records_between",
        lambda **kwargs: [
            {
                "account_id": "store_A",
                "shop_display_name": "兔兔潮玩屋",
                "count": 5,
            }
        ],
    )
    snapshot = collect_pdd_store_progress(reference_day=date(2026, 7, 6))
    assert snapshot.text == "兔兔潮玩屋：已发布5个"
    assert len(snapshot.shops) == 1
    assert snapshot.window_start.hour == 18
    assert snapshot.window_end.hour == 17

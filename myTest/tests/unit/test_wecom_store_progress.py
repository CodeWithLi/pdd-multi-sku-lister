"""企业微信日报店铺发布进度单元测试。"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

from pdd_agent.api.services.daily_shop_publish_stats import ShopPublishStat
from pdd_agent.core.report_time_window import report_listing_window
from pdd_agent.integrations.wecom.store_progress import (
    collect_pdd_store_progress,
    format_store_progress_lines,
)


def test_report_listing_window():
    start, end = report_listing_window(reference_day=date(2026, 7, 6))
    assert start == datetime(2026, 7, 5, 18, 1, 0)
    assert end == datetime(2026, 7, 6, 18, 0, 0)


def test_format_store_progress_lines():
    text = format_store_progress_lines(
        [
            ShopPublishStat(
                account_id="store_A",
                shop_display_name="兔兔潮玩屋",
                published_count=16,
                limited_time_success_count=12,
            ),
            ShopPublishStat(
                account_id="store_B",
                shop_display_name="可可爱爱巴布豆店铺",
                published_count=12,
                limited_time_success_count=0,
            ),
        ]
    )
    assert text == (
        "兔兔潮玩屋：已发布16个 + 限时限量购12个\n"
        "可可爱爱巴布豆店铺：已发布12个"
    )


def test_format_store_progress_skips_zero():
    text = format_store_progress_lines(
        [
            ShopPublishStat(account_id="a", shop_display_name="A店", published_count=0),
            ShopPublishStat(account_id="b", shop_display_name="B店", published_count=3),
        ]
    )
    assert text == "B店：已发布3个"


def test_collect_pdd_store_progress(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.wecom.store_progress.collect_shop_publish_report_snapshot",
        lambda **kwargs: (
            "2026-07-05 18:01",
            "2026-07-06 18:00",
            "兔兔潮玩屋：已发布5个 + 限时限量购3个",
            [
                ShopPublishStat(
                    account_id="store_A",
                    shop_display_name="兔兔潮玩屋",
                    published_count=5,
                    limited_time_success_count=3,
                )
            ],
        ),
    )
    snapshot = collect_pdd_store_progress(reference_day=date(2026, 7, 6))
    assert snapshot.text == "兔兔潮玩屋：已发布5个 + 限时限量购3个"
    assert len(snapshot.shops) == 1
    assert snapshot.window_start.hour == 18
    assert snapshot.window_end.hour == 18

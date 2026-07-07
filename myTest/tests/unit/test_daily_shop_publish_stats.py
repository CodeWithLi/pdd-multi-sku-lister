"""每日店铺发布进度统计单元测试。"""

from __future__ import annotations

from datetime import date, datetime

from pdd_agent.api.services.daily_shop_publish_stats import (
    ShopPublishStat,
    format_shop_publish_progress_line,
    format_shop_publish_progress_lines,
    merge_shop_publish_stats,
)


def test_format_shop_publish_progress_line_with_limited_time():
    line = format_shop_publish_progress_line(
        ShopPublishStat(
            account_id="store_A",
            shop_display_name="兔兔潮玩屋",
            published_count=16,
            limited_time_success_count=12,
        )
    )
    assert line == "兔兔潮玩屋：已发布16个 + 限时限量购12个"


def test_format_shop_publish_progress_line_without_limited_time():
    line = format_shop_publish_progress_line(
        ShopPublishStat(
            account_id="store_A",
            shop_display_name="兔兔潮玩屋",
            published_count=3,
            limited_time_success_count=0,
        )
    )
    assert line == "兔兔潮玩屋：已发布3个"


def test_merge_shop_publish_stats():
    stats = merge_shop_publish_stats(
        listing_rows=[
            {
                "account_id": "store_A",
                "shop_display_name": "兔兔潮玩屋",
                "count": 16,
            }
        ],
        limited_time_rows=[
            {"account_id": "store_A", "count": 12},
            {"account_id": "store_B", "count": 5},
        ],
    )
    by_account = {item.account_id: item for item in stats}
    assert by_account["store_A"].published_count == 16
    assert by_account["store_A"].limited_time_success_count == 12
    assert by_account["store_B"].published_count == 0
    assert by_account["store_B"].limited_time_success_count == 5


def test_format_shop_publish_progress_lines():
    text = format_shop_publish_progress_lines(
        [
            ShopPublishStat("a", "兔兔潮玩屋", 16, 12),
            ShopPublishStat("b", "B店", 0, 0),
        ]
    )
    assert text == "兔兔潮玩屋：已发布16个 + 限时限量购12个"


def test_summarize_shop_publish_stats_for_calendar_day(monkeypatch):
    from pdd_agent.api.services import daily_shop_publish_stats as module

    monkeypatch.setattr(module, "is_database_available", lambda: True)
    monkeypatch.setattr(
        module,
        "summarize_daily_listing_records",
        lambda listed_date: [
            {"account_id": "store_A", "shop_display_name": "兔兔潮玩屋", "count": 4}
        ],
    )
    monkeypatch.setattr(
        module,
        "summarize_limited_time_success_between",
        lambda **kwargs: [{"account_id": "store_A", "count": 2}],
    )
    monkeypatch.setattr(
        module,
        "summarize_activity_register_success_between",
        lambda **kwargs: [{"account_id": "store_A", "count": 1}],
    )
    monkeypatch.setattr(
        module,
        "summarize_promotion_success_between",
        lambda **kwargs: [],
    )
    stats = module.summarize_shop_publish_stats_for_calendar_day(date(2026, 7, 7))
    assert len(stats) == 1
    assert stats[0].published_count == 4
    assert stats[0].limited_time_success_count == 2

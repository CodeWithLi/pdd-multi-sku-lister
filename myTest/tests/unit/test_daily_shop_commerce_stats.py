"""活动报名/推广统计与店铺进度格式单元测试。"""

from __future__ import annotations

from pdd_agent.api.services.daily_shop_publish_stats import (
    ShopPublishStat,
    format_shop_publish_progress_line,
    merge_shop_publish_stats,
)
from pdd_agent.db.repositories import _count_success_items_from_run_result


def test_format_shop_publish_progress_line_full():
    line = format_shop_publish_progress_line(
        ShopPublishStat(
            account_id="store_A",
            shop_display_name="兔兔潮玩屋",
            published_count=16,
            limited_time_success_count=12,
            activity_register_success_count=8,
            promotion_success_count=5,
        )
    )
    assert line == (
        "兔兔潮玩屋：已发布16个 + 限时限量购12个 + 活动报名8个 + 推广5个"
    )


def test_merge_shop_publish_stats_with_activity_and_promotion():
    stats = merge_shop_publish_stats(
        listing_rows=[{"account_id": "store_A", "shop_display_name": "兔兔潮玩屋", "count": 3}],
        limited_time_rows=[{"account_id": "store_A", "count": 2}],
        activity_rows=[{"account_id": "store_A", "count": 4}],
        promotion_rows=[{"account_id": "store_B", "count": 1}],
    )
    by_account = {item.account_id: item for item in stats}
    assert by_account["store_A"].activity_register_success_count == 4
    assert by_account["store_B"].published_count == 0
    assert by_account["store_B"].promotion_success_count == 1


def test_count_success_items_from_run_result():
    assert _count_success_items_from_run_result(
        {"results": [{"status": "success"}, {"status": "failed"}]},
        payload={"pdd_product_ids": ["1", "2"]},
    ) == 1
    assert _count_success_items_from_run_result(
        {},
        payload={"pdd_product_ids": ["1", "2", "3"]},
    ) == 3

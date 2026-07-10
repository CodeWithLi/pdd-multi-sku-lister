"""限时限量购缺口统计单元测试。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.daily_shop_limited_time_gap_stats import summarize_limited_time_gap_between
from pdd_agent.api.services.published_limited_time_status_resolver import (
    LIMITED_TIME_STATUS_FAILED,
    LIMITED_TIME_STATUS_SUCCESS,
)


def test_summarize_limited_time_gap_between_groups_statuses():
    products = [
        SimpleNamespace(
            account_id="store_A",
            limited_time_status=LIMITED_TIME_STATUS_SUCCESS,
            limited_time_error="",
        ),
        SimpleNamespace(
            account_id="store_A",
            limited_time_status=LIMITED_TIME_STATUS_FAILED,
            limited_time_error="飞书数据缺失",
        ),
        SimpleNamespace(
            account_id="store_A",
            limited_time_status="",
            limited_time_error="",
        ),
    ]

    with patch(
        "pdd_agent.api.services.daily_shop_published_product_report_stats.is_database_available",
        return_value=True,
    ):
        with patch(
            "pdd_agent.api.services.daily_shop_published_product_report_stats.list_published_products_between",
            return_value=products,
        ):
            with patch(
                "pdd_agent.api.services.daily_shop_published_product_report_stats.resolve_account_display_name",
                return_value="兔兔潮玩屋",
            ):
                stats = summarize_limited_time_gap_between(
                    start=datetime(2026, 7, 8, 18, 1),
                    end=datetime(2026, 7, 9, 18, 0),
                )

    assert len(stats) == 1
    stat = stats[0]
    assert stat.shop_display_name == "兔兔潮玩屋"
    assert stat.published_count == 3
    assert stat.limited_time_success_count == 1
    assert stat.failed_count == 1
    assert stat.not_run_count == 1
    assert stat.failure_reasons[0].reason == "飞书数据缺失"

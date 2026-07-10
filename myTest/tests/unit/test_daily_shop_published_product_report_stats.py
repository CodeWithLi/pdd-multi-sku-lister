"""published_products 日报统计单元测试。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.daily_shop_published_product_report_stats import (
    summarize_published_product_report_between,
)
from pdd_agent.api.services.published_limited_time_status_resolver import (
    LIMITED_TIME_STATUS_FAILED,
    LIMITED_TIME_STATUS_SUCCESS,
)


def test_summarize_published_product_report_between():
    products = [
        SimpleNamespace(
            account_id="store_A",
            limited_time_status=LIMITED_TIME_STATUS_SUCCESS,
            limited_time_error="",
        ),
        SimpleNamespace(
            account_id="store_A",
            limited_time_status=LIMITED_TIME_STATUS_FAILED,
            limited_time_error="价格低于成本价",
        ),
        SimpleNamespace(
            account_id="store_B",
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
                side_effect=lambda account_id, **kwargs: {
                    "store_A": "兔兔潮玩屋",
                    "store_B": "甜甜圈时尚店",
                }.get(account_id, account_id),
            ):
                stats = summarize_published_product_report_between(
                    start=datetime(2026, 7, 8, 18, 1),
                    end=datetime(2026, 7, 9, 18, 0),
                )

    by_account = {item.account_id: item for item in stats}
    assert by_account["store_A"].published_count == 2
    assert by_account["store_A"].limited_time_success_count == 1
    assert by_account["store_A"].limited_time_failed_count == 1
    assert by_account["store_B"].published_count == 1
    assert by_account["store_B"].limited_time_not_run_count == 1

"""日报：统计窗口内上架商品的限时限量购失败 / 未跑缺口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pdd_agent.api.services.daily_shop_published_product_report_stats import (
    LimitedTimeFailureReasonStat,
    summarize_published_product_report_between,
)
from pdd_agent.db.session import is_database_available

__all__ = [
    "LimitedTimeFailureReasonStat",
    "ShopLimitedTimeGapStat",
    "gap_stats_by_account",
    "summarize_limited_time_gap_between",
]


@dataclass
class ShopLimitedTimeGapStat:
    account_id: str
    shop_display_name: str
    published_count: int = 0
    limited_time_success_count: int = 0
    failed_count: int = 0
    not_run_count: int = 0
    failure_reasons: list[LimitedTimeFailureReasonStat] = field(default_factory=list)


def summarize_limited_time_gap_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[ShopLimitedTimeGapStat]:
    """按店铺统计：窗口内已发布商品中限时限量购成功 / 失败 / 未跑。"""
    if not is_database_available():
        return []

    return [
        ShopLimitedTimeGapStat(
            account_id=item.account_id,
            shop_display_name=item.shop_display_name,
            published_count=item.published_count,
            limited_time_success_count=item.limited_time_success_count,
            failed_count=item.limited_time_failed_count,
            not_run_count=item.limited_time_not_run_count,
            failure_reasons=list(item.limited_time_failure_reasons),
        )
        for item in summarize_published_product_report_between(
            start=start,
            end=end,
            inclusive_end=inclusive_end,
        )
    ]


def gap_stats_by_account(stats: list[ShopLimitedTimeGapStat]) -> dict[str, ShopLimitedTimeGapStat]:
    return {
        str(item.account_id or "").strip(): item
        for item in stats
        if str(item.account_id or "").strip()
    }

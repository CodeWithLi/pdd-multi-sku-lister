"""日报：以 published_products 为准统计店铺发布与限时限量购进度。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select

from pdd_agent.api.services.published_limited_time_status_resolver import (
    LIMITED_TIME_STATUS_FAILED,
    LIMITED_TIME_STATUS_SUCCESS,
)
from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.db.models import PublishedProductORM
from pdd_agent.db.session import is_database_available, session_scope

_DEFAULT_FAILURE_REASON = "限时限量购未成功"
_MAX_REASON_LEN = 120


@dataclass
class LimitedTimeFailureReasonStat:
    reason: str
    count: int


@dataclass
class ShopPublishedProductReportStat:
    account_id: str
    shop_display_name: str
    published_count: int = 0
    limited_time_success_count: int = 0
    limited_time_failed_count: int = 0
    limited_time_not_run_count: int = 0
    limited_time_failure_reasons: list[LimitedTimeFailureReasonStat] = field(default_factory=list)

    @property
    def has_progress(self) -> bool:
        return int(self.published_count or 0) > 0


def _brief_limited_time_error(error: str) -> str:
    text = str(error or "").strip()
    if not text:
        return _DEFAULT_FAILURE_REASON
    line = text.split("\n", 1)[0].strip()
    if len(line) > _MAX_REASON_LEN:
        return f"{line[:_MAX_REASON_LEN]}..."
    return line


def _effective_published_at():
    return func.coalesce(PublishedProductORM.published_at, PublishedProductORM.created_at)


def list_published_products_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
    account_id: str = "",
    limit: int = 10000,
) -> list[PublishedProductORM]:
    """查询统计窗口内仍存在于 published_products 表的上架商品。"""
    if not is_database_available():
        return []
    cap = max(1, min(int(limit), 20000))
    published_at = _effective_published_at()
    with session_scope() as session:
        query = select(PublishedProductORM).where(published_at >= start)
        if inclusive_end:
            query = query.where(published_at <= end)
        else:
            query = query.where(published_at < end)
        account = str(account_id or "").strip()
        if account:
            query = query.where(PublishedProductORM.account_id == account)
        rows = list(
            session.scalars(
                query.order_by(published_at.desc(), PublishedProductORM.mapping_id.desc()).limit(cap)
            ).all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def summarize_published_product_report_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[ShopPublishedProductReportStat]:
    """按店铺汇总：窗口内已发布商品数 + 对应限时限量购成功/失败/未跑。"""
    rows = list_published_products_between(
        start=start,
        end=end,
        inclusive_end=inclusive_end,
    )
    if not rows:
        return []

    grouped: dict[str, list[PublishedProductORM]] = defaultdict(list)
    for row in rows:
        account_id = str(row.account_id or "").strip()
        if not account_id:
            continue
        grouped[account_id].append(row)

    stats: list[ShopPublishedProductReportStat] = []
    for account_id, products in grouped.items():
        success_count = 0
        failed_count = 0
        not_run_count = 0
        reason_counter: dict[str, int] = defaultdict(int)

        for product in products:
            status = str(product.limited_time_status or "").strip()
            error = str(product.limited_time_error or "").strip()
            if status == LIMITED_TIME_STATUS_SUCCESS:
                success_count += 1
                continue
            if status == LIMITED_TIME_STATUS_FAILED:
                failed_count += 1
                reason_counter[_brief_limited_time_error(error)] += 1
                continue
            not_run_count += 1

        failure_reasons = [
            LimitedTimeFailureReasonStat(reason=reason, count=count)
            for reason, count in sorted(
                reason_counter.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
        stats.append(
            ShopPublishedProductReportStat(
                account_id=account_id,
                shop_display_name=resolve_account_display_name(account_id) or account_id,
                published_count=len(products),
                limited_time_success_count=success_count,
                limited_time_failed_count=failed_count,
                limited_time_not_run_count=not_run_count,
                limited_time_failure_reasons=failure_reasons,
            )
        )

    stats.sort(
        key=lambda item: (
            item.published_count,
            item.limited_time_success_count,
            item.limited_time_failed_count,
        ),
        reverse=True,
    )
    return stats


def published_product_report_stats_by_account(
    stats: list[ShopPublishedProductReportStat],
) -> dict[str, ShopPublishedProductReportStat]:
    return {
        str(item.account_id or "").strip(): item
        for item in stats
        if str(item.account_id or "").strip()
    }

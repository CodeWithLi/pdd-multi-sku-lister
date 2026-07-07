"""每日店铺发布进度统计（上架 + 限时限量购 + 活动报名 + 推广）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.core.report_time_window import report_listing_window
from pdd_agent.db.repositories import (
    summarize_activity_register_success_between,
    summarize_daily_listing_records,
    summarize_daily_listing_records_between,
    summarize_limited_time_success_between,
    summarize_promotion_success_between,
)
from pdd_agent.db.session import is_database_available


@dataclass
class ShopPublishStat:
    account_id: str
    shop_display_name: str
    published_count: int
    limited_time_success_count: int = 0
    activity_register_success_count: int = 0
    promotion_success_count: int = 0

    @property
    def count(self) -> int:
        """兼容旧字段：已发布数量。"""
        return self.published_count

    @property
    def has_progress(self) -> bool:
        return any(
            int(value or 0) > 0
            for value in (
                self.published_count,
                self.limited_time_success_count,
                self.activity_register_success_count,
                self.promotion_success_count,
            )
        )


def calendar_day_bounds(target: date) -> tuple[datetime, datetime]:
    """自然日统计窗口：[当天 00:00, 次日 00:00)。"""
    start = datetime(target.year, target.month, target.day)
    end = start + timedelta(days=1)
    return start, end


def _resolve_shop_name(account_id: str, shop_display_name: str = "") -> str:
    name = str(shop_display_name or "").strip()
    if name:
        return name
    return resolve_account_display_name(account_id) or account_id


def merge_shop_publish_stats(
    *,
    listing_rows: list[dict[str, str | int]],
    limited_time_rows: list[dict[str, str | int]] | None = None,
    activity_rows: list[dict[str, str | int]] | None = None,
    promotion_rows: list[dict[str, str | int]] | None = None,
) -> list[ShopPublishStat]:
    """合并上架、限时限量购、活动报名与推广统计（按 account_id）。"""
    merged: dict[str, ShopPublishStat] = {}

    def _ensure(account_id: str, shop_display_name: str = "") -> ShopPublishStat:
        key = account_id or shop_display_name or "unknown"
        current = merged.get(key)
        if current:
            if not current.shop_display_name and shop_display_name:
                current.shop_display_name = shop_display_name
            return current
        stat = ShopPublishStat(
            account_id=account_id,
            shop_display_name=_resolve_shop_name(account_id, shop_display_name),
            published_count=0,
            limited_time_success_count=0,
            activity_register_success_count=0,
            promotion_success_count=0,
        )
        merged[key] = stat
        return stat

    for row in listing_rows:
        account_id = str(row.get("account_id") or "").strip()
        shop_name = str(row.get("shop_display_name") or "").strip()
        stat = _ensure(account_id, shop_name)
        stat.published_count = int(row.get("count") or 0)
        if not stat.shop_display_name:
            stat.shop_display_name = _resolve_shop_name(account_id, shop_name)

    for rows, attr in (
        (limited_time_rows or [], "limited_time_success_count"),
        (activity_rows or [], "activity_register_success_count"),
        (promotion_rows or [], "promotion_success_count"),
    ):
        for row in rows:
            account_id = str(row.get("account_id") or "").strip()
            stat = _ensure(account_id)
            setattr(stat, attr, int(row.get("count") or 0))

    items = list(merged.values())
    items.sort(
        key=lambda item: (
            item.published_count,
            item.limited_time_success_count,
            item.activity_register_success_count,
            item.promotion_success_count,
        ),
        reverse=True,
    )
    return items


def format_shop_publish_progress_line(stat: ShopPublishStat) -> str:
    """格式：店铺名：已发布 N 个 + 限时限量购 M 个 + 活动报名 X 个 + 推广 Y 个。"""
    name = stat.shop_display_name or stat.account_id
    segments = [f"已发布{int(stat.published_count or 0)}个"]
    if int(stat.limited_time_success_count or 0) > 0:
        segments.append(f"限时限量购{int(stat.limited_time_success_count)}个")
    if int(stat.activity_register_success_count or 0) > 0:
        segments.append(f"活动报名{int(stat.activity_register_success_count)}个")
    if int(stat.promotion_success_count or 0) > 0:
        segments.append(f"推广{int(stat.promotion_success_count)}个")
    return f"{name}：" + " + ".join(segments)


def format_shop_publish_progress_lines(stats: list[ShopPublishStat]) -> str:
    lines: list[str] = []
    for stat in stats:
        if not stat.has_progress:
            continue
        lines.append(format_shop_publish_progress_line(stat))
    return "\n".join(lines)


def summarize_shop_publish_stats_for_report_day(
    *,
    reference_day: date | None = None,
    now: datetime | None = None,
) -> list[ShopPublishStat]:
    """按日报窗口汇总（昨天 18:01 ~ 今天 18:00）。"""
    start, end = report_listing_window(reference_day=reference_day, now=now)
    return summarize_shop_publish_stats_between(
        start=start,
        end=end,
        inclusive_end=True,
    )


def summarize_shop_publish_stats_for_calendar_day(
    listed_date: date,
) -> list[ShopPublishStat]:
    """按自然日汇总各店铺上架数与运营链路成功数。"""
    if not is_database_available():
        return []
    start, end = calendar_day_bounds(listed_date)
    listing_rows = summarize_daily_listing_records(listed_date=listed_date)
    limited_rows = summarize_limited_time_success_between(
        start=start,
        end=end,
        inclusive_end=False,
    )
    activity_rows = summarize_activity_register_success_between(
        start=start,
        end=end,
        inclusive_end=False,
    )
    promotion_rows = summarize_promotion_success_between(
        start=start,
        end=end,
        inclusive_end=False,
    )
    return merge_shop_publish_stats(
        listing_rows=listing_rows,
        limited_time_rows=limited_rows,
        activity_rows=activity_rows,
        promotion_rows=promotion_rows,
    )


def summarize_shop_publish_stats_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[ShopPublishStat]:
    """按自定义时间段汇总（企业微信日报窗口等）。"""
    if not is_database_available():
        return []
    listing_rows = summarize_daily_listing_records_between(start=start, end=end)
    limited_rows = summarize_limited_time_success_between(
        start=start,
        end=end,
        inclusive_end=inclusive_end,
    )
    activity_rows = summarize_activity_register_success_between(
        start=start,
        end=end,
        inclusive_end=inclusive_end,
    )
    promotion_rows = summarize_promotion_success_between(
        start=start,
        end=end,
        inclusive_end=inclusive_end,
    )
    return merge_shop_publish_stats(
        listing_rows=listing_rows,
        limited_time_rows=limited_rows,
        activity_rows=activity_rows,
        promotion_rows=promotion_rows,
    )


def enrich_listing_shop_summaries(
    listing_rows: list[dict[str, str | int]],
    *,
    listed_date: date,
) -> list[dict[str, str | int]]:
    """为每日上架汇总附加运营链路成功数。"""
    start, end = calendar_day_bounds(listed_date)
    return enrich_listing_shop_summaries_between(
        listing_rows,
        start=start,
        end=end,
        inclusive_end=False,
    )


def enrich_listing_shop_summaries_between(
    listing_rows: list[dict[str, str | int]],
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[dict[str, str | int]]:
    """为时间段上架汇总附加运营链路成功数。"""
    limited_rows = summarize_limited_time_success_between(
        start=start,
        end=end,
        inclusive_end=inclusive_end,
    )
    activity_rows = summarize_activity_register_success_between(
        start=start,
        end=end,
        inclusive_end=inclusive_end,
    )
    promotion_rows = summarize_promotion_success_between(
        start=start,
        end=end,
        inclusive_end=inclusive_end,
    )
    limited_by_account = {
        str(row.get("account_id") or "").strip(): int(row.get("count") or 0)
        for row in limited_rows
    }
    activity_by_account = {
        str(row.get("account_id") or "").strip(): int(row.get("count") or 0)
        for row in activity_rows
    }
    promotion_by_account = {
        str(row.get("account_id") or "").strip(): int(row.get("count") or 0)
        for row in promotion_rows
    }
    enriched: list[dict[str, str | int]] = []
    for row in listing_rows:
        account_id = str(row.get("account_id") or "").strip()
        item = dict(row)
        item["limited_time_success_count"] = limited_by_account.get(account_id, 0)
        item["activity_register_success_count"] = activity_by_account.get(account_id, 0)
        item["promotion_success_count"] = promotion_by_account.get(account_id, 0)
        enriched.append(item)
    return enriched


def count_limited_time_success_total(stats: list[ShopPublishStat]) -> int:
    return sum(int(stat.limited_time_success_count or 0) for stat in stats)


def count_activity_register_success_total(stats: list[ShopPublishStat]) -> int:
    return sum(int(stat.activity_register_success_count or 0) for stat in stats)


def count_promotion_success_total(stats: list[ShopPublishStat]) -> int:
    return sum(int(stat.promotion_success_count or 0) for stat in stats)

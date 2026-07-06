"""企业微信日报：拼多多店铺发布进度（自定义统计窗口）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import summarize_daily_listing_records_between
from pdd_agent.db.session import is_database_available

logger = get_logger(__name__)

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    TZ = timezone(timedelta(hours=8))

# 日报 18:00 发送，统计窗口为昨天 18:01 ~ 今天 17:00
WINDOW_START_HOUR = 18
WINDOW_START_MINUTE = 1
WINDOW_END_HOUR = 17
WINDOW_END_MINUTE = 0


@dataclass
class StoreListingSummary:
    account_id: str
    shop_display_name: str
    count: int


@dataclass
class StoreProgressSnapshot:
    window_start: datetime
    window_end: datetime
    shops: list[StoreListingSummary]
    text: str


def today_in_tz() -> date:
    return datetime.now(TZ).date()


def report_listing_window(
    *,
    reference_day: date | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """计算日报使用的上架统计窗口（昨天 18:01 ~ 今天 17:00，含边界）。"""
    ref = now or datetime.now(TZ)
    today = reference_day or ref.date()
    yesterday = today - timedelta(days=1)
    start = datetime(
        yesterday.year,
        yesterday.month,
        yesterday.day,
        WINDOW_START_HOUR,
        WINDOW_START_MINUTE,
        0,
    )
    end = datetime(
        today.year,
        today.month,
        today.day,
        WINDOW_END_HOUR,
        WINDOW_END_MINUTE,
        0,
    )
    return start, end


def _resolve_shop_name(account_id: str, shop_display_name: str) -> str:
    name = str(shop_display_name or "").strip()
    if name:
        return name
    return resolve_account_display_name(account_id) or account_id


def format_store_progress_lines(shops: list[StoreListingSummary]) -> str:
    """格式：店铺名：已发布 N 个（每行一条，仅 PDD 有数据的店铺）。"""
    lines: list[str] = []
    for shop in shops:
        if shop.count <= 0:
            continue
        name = shop.shop_display_name or shop.account_id
        lines.append(f"{name}：已发布{shop.count}个")
    return "\n".join(lines)


def collect_pdd_store_progress(
    *,
    reference_day: date | None = None,
    now: datetime | None = None,
) -> StoreProgressSnapshot:
    """采集拼多多店铺在日报窗口内的发布进度。"""
    start, end = report_listing_window(reference_day=reference_day, now=now)
    shops: list[StoreListingSummary] = []

    if is_database_available():
        try:
            rows = summarize_daily_listing_records_between(start=start, end=end)
            for row in rows:
                account_id = str(row.get("account_id") or "").strip()
                count = int(row.get("count") or 0)
                if count <= 0:
                    continue
                shops.append(
                    StoreListingSummary(
                        account_id=account_id,
                        shop_display_name=_resolve_shop_name(
                            account_id,
                            str(row.get("shop_display_name") or ""),
                        ),
                        count=count,
                    )
                )
        except Exception:
            logger.exception("collect pdd store progress failed")

    return StoreProgressSnapshot(
        window_start=start,
        window_end=end,
        shops=shops,
        text=format_store_progress_lines(shops),
    )

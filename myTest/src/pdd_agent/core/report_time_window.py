"""企业微信日报与店铺统计共用的统计窗口定义。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    TZ = timezone(timedelta(hours=8))

# 日报约 18:00 发送，统计窗口为昨天 18:01 ~ 今天 18:00（含边界）
WINDOW_START_HOUR = 18
WINDOW_START_MINUTE = 1
WINDOW_END_HOUR = 18
WINDOW_END_MINUTE = 0

REPORT_WINDOW_DESCRIPTION = "昨天 18:01 ~ 今天 18:00（与 PDD 日报一致）"
CALENDAR_WINDOW_DESCRIPTION = "自然日 00:00 ~ 24:00"


def today_in_tz() -> date:
    return datetime.now(TZ).date()


def report_listing_window(
    *,
    reference_day: date | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """计算日报统计窗口（昨天 18:01 ~ 今天 18:00，含边界）。"""
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


def format_report_window_label(start: datetime, end: datetime) -> str:
    """短标签，用于 Markdown：07-05 18:01 ~ 07-06 18:00。"""
    return f"{start.strftime('%m-%d %H:%M')} ~ {end.strftime('%m-%d %H:%M')}"


def format_report_window_iso(start: datetime, end: datetime) -> tuple[str, str]:
    """完整 ISO 风格时间，用于 API 响应。"""
    return (
        start.strftime("%Y-%m-%d %H:%M"),
        end.strftime("%Y-%m-%d %H:%M"),
    )

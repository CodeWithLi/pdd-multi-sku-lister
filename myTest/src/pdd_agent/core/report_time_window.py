"""企业微信日报与店铺统计共用的统计窗口定义。"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ReportListingWindowBounds:
    """店铺发布进度默认统计窗口边界（相对 reference_day 的前一天/当天）。"""

    start_hour: int = WINDOW_START_HOUR
    start_minute: int = WINDOW_START_MINUTE
    end_hour: int = WINDOW_END_HOUR
    end_minute: int = WINDOW_END_MINUTE

    def describe(self) -> str:
        return (
            f"昨天 {int(self.start_hour):02d}:{int(self.start_minute):02d} "
            f"~ 今天 {int(self.end_hour):02d}:{int(self.end_minute):02d}"
        )


def today_in_tz() -> date:
    return datetime.now(TZ).date()


def parse_report_window_datetime(text: str) -> datetime | None:
    """解析统计窗口时间，支持 YYYY-MM-DD HH:MM(:SS)。"""
    raw = str(text or "").strip().replace("T", " ")
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def report_listing_window(
    *,
    reference_day: date | None = None,
    now: datetime | None = None,
    bounds: ReportListingWindowBounds | None = None,
) -> tuple[datetime, datetime]:
    """计算日报统计窗口（默认昨天 start ~ 今天 end，含边界）。"""
    window = bounds or ReportListingWindowBounds()
    ref = now or datetime.now(TZ)
    today = reference_day or ref.date()
    yesterday = today - timedelta(days=1)
    start = datetime(
        yesterday.year,
        yesterday.month,
        yesterday.day,
        int(window.start_hour),
        int(window.start_minute),
        0,
    )
    end = datetime(
        today.year,
        today.month,
        today.day,
        int(window.end_hour),
        int(window.end_minute),
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

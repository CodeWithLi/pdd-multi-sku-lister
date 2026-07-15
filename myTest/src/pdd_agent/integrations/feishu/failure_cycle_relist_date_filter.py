"""失败日志循环上架 — 按飞书「日期」抓取起始日筛选。"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


_DATE_RE = re.compile(
    r"(?P<y>\d{4})[-/\.年](?P<m>\d{1,2})[-/\.月](?P<d>\d{1,2})",
)


def normalize_fetch_after_date(value: Any) -> str:
    """配置值归一为 YYYY-MM-DD；空表示不按日筛选。"""
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = parse_failure_log_date(text)
    if parsed is None:
        return ""
    return parsed.isoformat()


def parse_failure_log_date(value: Any) -> date | None:
    """解析飞书「日期」或配置抓取日：支持 YYYY-MM-DD / YYYY/MM/DD / 带时间 / 毫秒时间戳。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts).date()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_failure_log_date(int(text))

    match = _DATE_RE.search(text)
    if match:
        try:
            return date(
                int(match.group("y")),
                int(match.group("m")),
                int(match.group("d")),
            )
        except ValueError:
            return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def record_date_meets_fetch_after(*, record_date: Any, fetch_after_date: Any) -> bool:
    """
    记录日期是否满足「抓取时间」：记录日 >= 配置日起。

    - 未配置抓取日 → 通过
    - 已配置但记录无日期 / 无法解析 → 不通过（避免旧脏数据混入）
    """
    after = normalize_fetch_after_date(fetch_after_date)
    if not after:
        return True
    after_d = parse_failure_log_date(after)
    if after_d is None:
        return True
    record_d = parse_failure_log_date(record_date)
    if record_d is None:
        return False
    return record_d >= after_d


def fetch_after_date_to_feishu_ms(fetch_after_date: Any) -> int | None:
    """飞书 DateTime 筛选用：抓取日起 00:00 的本地毫秒时间戳。"""
    normalized = normalize_fetch_after_date(fetch_after_date)
    if not normalized:
        return None
    d = parse_failure_log_date(normalized)
    if d is None:
        return None
    return int(datetime(d.year, d.month, d.day, 0, 0, 0).timestamp() * 1000)

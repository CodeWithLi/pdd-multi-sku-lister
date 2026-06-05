"""下架时间门槛解析与校验（严格模式，防止误下架）。"""
from __future__ import annotations

import re
from datetime import datetime

# 创建时间常见格式：2024-06-04 14:28 或带秒
CREATED_AT_REGEXES = (
    re.compile(r"(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"),
    re.compile(r"(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2})"),
)

PRODUCT_ID_REGEXES = (
    re.compile(r"ID[：:\s]*(\d{10,})"),
    re.compile(r"商品ID[：:\s]*(\d{10,})"),
)

THRESHOLD_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def parse_threshold(value: str) -> datetime:
    """解析用户配置的下架时间门槛。"""
    text = (value or "").strip()
    if not text:
        raise ValueError("未配置「最早可下架创建时间」，请先设置后再执行")

    for fmt in THRESHOLD_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d":
                return dt.replace(hour=0, minute=0, second=0)
            return dt
        except ValueError:
            continue
    raise ValueError(f"无法解析下架时间门槛：{text}（示例：2026-06-04 14:00:00）")


def extract_created_at_from_text(text: str) -> datetime | None:
    """从表格行文本中提取创建时间（取第一个合法匹配）。"""
    if not text:
        return None
    for pattern in CREATED_AT_REGEXES:
        m = pattern.search(text)
        if not m:
            continue
        raw = m.group(1)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return None


def extract_product_id_from_text(text: str) -> str | None:
    """从行文本提取商品 ID，用于日志与二次定位。"""
    if not text:
        return None
    for pattern in PRODUCT_ID_REGEXES:
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def is_eligible_for_delist(created_at: datetime, threshold: datetime) -> bool:
    """
    仅当创建时间严格晚于门槛时才允许下架。
    created_at == threshold 或更早 → 一律不允许。
    """
    return created_at > threshold


def format_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

"""失败日志循环上架：排除失败原因短语（支持多条）。"""

from __future__ import annotations

from typing import Any


def normalize_exclude_failure_reason_phrases(value: Any) -> list[str]:
    """将配置值规范为去重后的排除短语列表。

    兼容历史单条字符串；也支持换行/逗号分隔的多条文本。
    """
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.replace("\r\n", "\n").replace("\r", "\n")
        parts: list[str] = []
        for line in raw.split("\n"):
            for chunk in line.split(","):
                text = str(chunk or "").strip()
                if text:
                    parts.append(text)
        return _dedupe_phrases(parts)
    if isinstance(value, (list, tuple, set)):
        parts = [str(x).strip() for x in value if str(x).strip()]
        return _dedupe_phrases(parts)
    return []


def _dedupe_phrases(phrases: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for phrase in phrases:
        if phrase in seen:
            continue
        seen.add(phrase)
        ordered.append(phrase)
    return ordered


def failure_reason_matches_exclude_phrases(
    failure_reason: str,
    exclude_phrases: list[str] | str | Any,
) -> bool:
    """失败原因是否命中任一排除短语（包含匹配）。"""
    phrases = normalize_exclude_failure_reason_phrases(exclude_phrases)
    if not phrases:
        return False
    text = str(failure_reason or "")
    return any(phrase in text for phrase in phrases)

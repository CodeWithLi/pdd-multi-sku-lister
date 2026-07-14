"""规格校验填表失败说明（抖店）。"""

from __future__ import annotations

from typing import Any


def format_spec_fill_verify_reason(fill_stats: dict[str, Any] | None) -> str:
    stats = fill_stats or {}
    issues = list(stats.get("verify_issues") or stats.get("failed_items") or [])
    if not issues:
        return str(stats.get("message") or "规格填表校验未通过")
    lines: list[str] = []
    for idx, item in enumerate(issues[:8], start=1):
        if not isinstance(item, dict):
            continue
        combo = str(item.get("combo_folder") or "").strip()
        style = str(item.get("style") or item.get("style_name") or "").strip()
        size = str(item.get("size") or item.get("model_name") or "").strip()
        reason = str(item.get("reason") or "").strip()
        detail = str(item.get("detail") or "").strip()
        identity = combo or (f"{style}/{size}" if style and size else style or size)
        tail = reason
        if detail and detail != reason:
            tail = f"{reason}: {detail}" if reason else detail
        lines.append(f"{idx}. {identity} {tail}".strip())
    return "\n".join(lines) if lines else "规格填表校验未通过"

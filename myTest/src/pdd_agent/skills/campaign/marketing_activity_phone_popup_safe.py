"""
营销活动 — 安全关闭「营销联系电话」浮层。

与 marketing_activities.py 解耦：避免 _click_blank_to_dismiss_popup 误点左侧菜单（意见反馈等）。
"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)

# 原 _collect_blank_click_points 中会点到侧栏的坐标名，守卫版一律排除。
UNSAFE_BLANK_POINT_NAMES = frozenset(
    {
        "left_sidebar",
        "far_left",
        "left_content",
    }
)


def _safe_log(account_id: str, message: str, **extra: Any) -> None:
    prefix = f"[{account_id}] [营销电话浮层守卫]"
    parts = [f"{key}={value}" for key, value in extra.items() if value is not None and value != ""]
    line = f"{prefix} {message}"
    if parts:
        line = f"{line} | {' '.join(parts)}"
    logger.info(line)
    print(line, flush=True)


def collect_safe_blank_click_points(popup_rect: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """在原有空白点击点基础上去掉侧栏区域。"""
    from pdd_agent.skills.campaign.marketing_activities import _collect_blank_click_points

    points = _collect_blank_click_points(popup_rect)
    return [item for item in points if str(item.get("name") or "") not in UNSAFE_BLANK_POINT_NAMES]


def _click_safe_blank_to_dismiss_popup(page: DpPage, popup_rect: dict[str, Any] | None = None) -> dict[str, Any]:
    from pdd_agent.skills.campaign.marketing_activities import (
        _find_marketing_header_blank_point,
        _playwright_mouse_click,
        _press_escape,
    )

    actions: list[dict[str, Any]] = []

    header_blank = _find_marketing_header_blank_point(page)
    actions.append({"probe": header_blank})
    if header_blank.get("found"):
        primary = _playwright_mouse_click(page, float(header_blank["x"]), float(header_blank["y"]))
        actions.append({**primary, "target": header_blank.get("method", "header_blank")})
        if primary.get("clicked"):
            time.sleep(0.45)
            for offset_name, dx, dy in (
                ("header_blank_offset_left", -28, 0),
                ("header_blank_offset_down", 0, 18),
                ("header_blank_offset_right", 24, 0),
            ):
                offset_click = _playwright_mouse_click(
                    page,
                    float(header_blank["x"]) + dx,
                    float(header_blank["y"]) + dy,
                )
                actions.append({**offset_click, "target": offset_name})
                if offset_click.get("clicked"):
                    time.sleep(0.25)

    escape_result = _press_escape(page)
    actions.append(escape_result)
    if escape_result.get("pressed"):
        time.sleep(0.35)

    for point in collect_safe_blank_click_points(popup_rect):
        click_result = _playwright_mouse_click(page, point["x"], point["y"])
        actions.append({**click_result, "target": point["name"]})
        if click_result.get("clicked"):
            time.sleep(0.35)

    clicked_actions = [item for item in actions if item.get("clicked") or item.get("pressed")]
    return {
        "clicked": bool(clicked_actions),
        "actions": actions,
        "safe_mode": True,
    }


def dismiss_marketing_phone_popup_safe(
    page: DpPage,
    account_id: str = "",
    *,
    max_attempts: int = 4,
) -> dict[str, Any]:
    """安全版关闭营销电话浮层：仅点标题区空白 + Escape + 内容区，不点侧栏。"""
    from pdd_agent.skills.campaign.marketing_activities import _read_marketing_phone_popup

    attempts: list[dict[str, Any]] = []
    for _ in range(max_attempts):
        state = _read_marketing_phone_popup(page)
        if not state.get("visible"):
            return {
                "dismissed": True,
                "already_closed": not attempts,
                "attempts": attempts,
                "safe_mode": True,
            }

        click_result = _click_safe_blank_to_dismiss_popup(page, state.get("rect") or {})
        attempts.append({"before": state, "click": click_result})
        time.sleep(0.9)

        after = _read_marketing_phone_popup(page)
        if not after.get("visible"):
            if account_id:
                _safe_log(account_id, "已关闭营销联系电话提示浮层", method="safe_blank_click")
            return {
                "dismissed": True,
                "attempts": attempts,
                "after": after,
                "safe_mode": True,
            }

    final = _read_marketing_phone_popup(page)
    return {
        "dismissed": not final.get("visible"),
        "attempts": attempts,
        "after": final,
        "safe_mode": True,
    }

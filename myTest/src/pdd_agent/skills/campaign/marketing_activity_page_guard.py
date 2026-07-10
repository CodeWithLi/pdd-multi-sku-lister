"""
营销活动页 — 标签焦点与页面就绪守卫。

与 marketing_activities.py 解耦：处理 about:blank / 错标签 / 加载中 导致的搜索框找不到。
"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.logging import get_logger
from pdd_agent.skills.campaign.marketing_activity_blocking_modal_dismiss import (
    dismiss_one_marketing_blocking_modal,
)
from pdd_agent.skills.campaign.marketing_activity_pending_section_guard import (
    dismiss_unexpected_pending_modals,
    prepare_marketing_registration_surface,
)
from pdd_agent.skills.campaign.marketing_activity_search_input_scope import (
    find_activity_search_input_scoped,
)
from pdd_agent.skills.campaign.limited_time import _bind_page, _body_text, _live_context_pages

logger = get_logger(__name__)

MARKETING_ACTIVITIES_URL_PARTS = ("/act/index", "/act/signup", "actHomeActivityType")
WRONG_FOCUS_URL_PARTS = ("about:blank", "chrome://newtab/", "/pg/feedback", "multi-quick-channel")
MARKETING_PAGE_MARKERS = ("营销活动报名", "活动大厅", "我能参加的活动", "全部活动", "报名记录")
LOADING_MARKERS = ("加载中", "正在加载")


def _guard_log(account_id: str, step: str, message: str, **extra: Any) -> None:
    prefix = f"[{account_id}] [营销活动页守卫][{step}]"
    parts = [f"{key}={value}" for key, value in extra.items() if value is not None and value != ""]
    line = f"{prefix} {message}"
    if parts:
        line = f"{line} | {' '.join(parts)}"
    logger.info(line)
    print(line, flush=True)


def is_marketing_activities_url(url: str) -> bool:
    safe = str(url or "")
    if any(part in safe for part in WRONG_FOCUS_URL_PARTS):
        return False
    return any(part in safe for part in MARKETING_ACTIVITIES_URL_PARTS)


def is_wrong_focus_url(url: str) -> bool:
    safe = str(url or "")
    return any(part in safe for part in WRONG_FOCUS_URL_PARTS)


def _page_has_marketing_markers(text: str) -> bool:
    body = str(text or "")
    return any(marker in body for marker in MARKETING_PAGE_MARKERS)


def _page_is_loading(text: str) -> bool:
    body = str(text or "")
    return any(marker in body for marker in LOADING_MARKERS)


def _score_marketing_tab(url: str, text: str, has_search_input: bool) -> int:
    score = 0
    if is_marketing_activities_url(url):
        score += 40
    if _page_has_marketing_markers(text):
        score += 30
    if has_search_input:
        score += 50
    if _page_is_loading(text):
        score -= 20
    if is_wrong_focus_url(url):
        score -= 100
    return score


def _read_search_input_state(page: DpPage) -> dict[str, Any]:
    return find_activity_search_input_scoped(page)


def _close_blank_tabs(page: DpPage, account_id: str) -> list[str]:
    closed: list[str] = []
    raw_page = getattr(page, "_page", None)
    pages = _live_context_pages(page)
    if len(pages) <= 1:
        return closed

    for item in list(pages):
        if item is raw_page:
            continue
        try:
            url = str(item.url or "")
        except Exception:
            continue
        if url not in ("about:blank", "chrome://newtab/"):
            continue
        try:
            if not item.is_closed():
                item.close()
                closed.append(url)
        except Exception:
            continue

    if closed:
        _guard_log(account_id, "关空白标签", "已关闭", closed=closed)
    return closed


def ensure_marketing_activities_tab_focus(page: DpPage, account_id: str) -> dict[str, Any]:
    """将 Playwright 绑定切回营销活动大厅标签，避免停在 about:blank / 意见反馈等页。"""
    from pdd_agent.skills.campaign.marketing_activities import _close_multi_quick_channel_tabs

    multi_quick = _close_multi_quick_channel_tabs(page, account_id)
    blank_closed = _close_blank_tabs(page, account_id)

    candidates: list[dict[str, Any]] = []
    best_meta: dict[str, Any] | None = None
    best_page: Any = None
    for item in _live_context_pages(page):
        try:
            url = str(item.url or "")
        except Exception:
            continue
        if is_wrong_focus_url(url):
            continue
        try:
            _bind_page(page, item)
            text = _body_text(page)
            search_state = _read_search_input_state(page)
        except Exception as exc:
            text = ""
            search_state = {"found": False, "reason": str(exc)}
        meta = {
            "url": url,
            "text_sample": text[:120],
            "search_found": bool(search_state.get("found")),
            "score": _score_marketing_tab(url, text, bool(search_state.get("found"))),
        }
        candidates.append(meta)
        if best_meta is None or meta["score"] > best_meta["score"]:
            best_meta = meta
            best_page = item

    if not candidates:
        return {
            "focused": False,
            "reason": "no_candidate_tabs",
            "multi_quick": multi_quick,
            "blank_closed": blank_closed,
            "current_url": str(getattr(page, "url", "") or ""),
        }

    best = max(candidates, key=lambda item: item["score"])
    if best["score"] < 20:
        return {
            "focused": False,
            "reason": "no_suitable_marketing_tab",
            "candidates": candidates,
            "multi_quick": multi_quick,
            "blank_closed": blank_closed,
            "current_url": str(getattr(page, "url", "") or ""),
        }

    target = best_page
    if target is None:
        return {
            "focused": False,
            "reason": "best_page_missing",
            "candidates": candidates,
            "multi_quick": multi_quick,
            "blank_closed": blank_closed,
            "current_url": str(getattr(page, "url", "") or ""),
        }
    _bind_page(page, target)
    try:
        target.bring_to_front()
    except Exception:
        pass

    _guard_log(
        account_id,
        "切标签",
        "已聚焦营销活动页",
        url=best["url"],
        search_found=best["search_found"],
        score=best["score"],
    )
    return {
        "focused": True,
        "url": best["url"],
        "search_found": best["search_found"],
        "score": best["score"],
        "candidates": candidates,
        "multi_quick": multi_quick,
        "blank_closed": blank_closed,
    }


def wait_for_activity_search_input(
    page: DpPage,
    account_id: str,
    *,
    timeout: int = 20,
) -> dict[str, Any]:
    """轮询等待活动搜索框出现，期间自动纠正标签焦点。"""
    last_focus: dict[str, Any] = {}
    last_state: dict[str, Any] = {"found": False, "reason": "not_started"}
    last_loading = True

    for tick in range(max(1, timeout)):
        last_focus = ensure_marketing_activities_tab_focus(page, account_id)
        dismiss_one_marketing_blocking_modal(page, account_id)
        dismiss_unexpected_pending_modals(page, account_id)
        if tick >= 2:
            prepare_marketing_registration_surface(page, account_id)
        text = _body_text(page)
        last_loading = _page_is_loading(text)
        last_state = _read_search_input_state(page)
        if last_state.get("found"):
            _guard_log(
                account_id,
                "搜索框就绪",
                "已找到",
                tick=tick,
                method=last_state.get("method"),
                placeholder=last_state.get("placeholder"),
                section_score=last_state.get("section_score"),
            )
            return {
                "ready": True,
                "found": True,
                "tick": tick,
                "loading": last_loading,
                "focus": last_focus,
                "search_input": last_state,
                "current_url": str(getattr(page, "url", "") or ""),
            }
        if tick in {0, timeout - 1} or tick % 3 == 0:
            _guard_log(
                account_id,
                "等待搜索框",
                "轮询中",
                tick=tick + 1,
                total=timeout,
                loading=last_loading,
                reason=last_state.get("reason"),
                url=str(getattr(page, "url", "") or ""),
            )
        time.sleep(1)

    _guard_log(
        account_id,
        "等待搜索框",
        "超时",
        tick=timeout,
        reason=last_state.get("reason"),
        search_input=last_state,
    )

    return {
        "ready": False,
        "found": False,
        "tick": timeout,
        "loading": last_loading,
        "focus": last_focus,
        "search_input": last_state,
        "current_url": str(getattr(page, "url", "") or ""),
        "reason": "search_input_timeout",
    }


def prepare_marketing_activities_page_after_open(
    page: DpPage,
    account_id: str,
    *,
    wait_timeout: int = 20,
) -> dict[str, Any]:
    """打开营销活动页之后的守卫：纠正标签 + 等待搜索框就绪。"""
    focus = ensure_marketing_activities_tab_focus(page, account_id)
    wait_result = wait_for_activity_search_input(page, account_id, timeout=wait_timeout)
    return {
        "focus": focus,
        "wait": wait_result,
        "ready": bool(wait_result.get("found")),
    }

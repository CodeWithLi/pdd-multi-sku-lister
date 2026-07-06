"""
营销活动搜索 — 带页面守卫的搜索流程。

与 marketing_activities.search_marketing_activity 解耦，供 Campaign Agent 引用。
"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.config import AccountConfig
from pdd_agent.core.logging import get_logger
from pdd_agent.skills.campaign.marketing_activity_page_guard import (
    ensure_marketing_activities_tab_focus,
    prepare_marketing_activities_page_after_open,
    wait_for_activity_search_input,
)
from pdd_agent.skills.campaign.marketing_activity_phone_popup_safe import dismiss_marketing_phone_popup_safe

logger = get_logger(__name__)


def _search_log(account_id: str, step: str, message: str, **extra: Any) -> None:
    prefix = f"[{account_id}] [营销活动搜索守卫][{step}]"
    parts = [f"{key}={value}" for key, value in extra.items() if value is not None and value != ""]
    line = f"{prefix} {message}"
    if parts:
        line = f"{line} | {' '.join(parts)}"
    logger.info(line)
    print(line, flush=True)


def search_marketing_activity_guarded(
    page: DpPage,
    account_id: str,
    activity_id: str,
    account: AccountConfig | None = None,
) -> dict[str, Any]:
    """
    打开营销活动页 → 守卫纠正标签/等待搜索框 → 搜索活动 ID。

    行为与 search_marketing_activity 一致，但在找搜索框前增加守卫逻辑。
    """
    from pdd_agent.skills.campaign.limited_time import _click_text, _dismiss_message_popup
    from pdd_agent.skills.campaign.marketing_activities import (
        _click_activity_search_button,
        _close_multi_quick_channel_tabs,
        _fill_activity_search_input,
        _find_activity_search_input,
        _install_multi_quick_tab_blocker,
        _open_marketing_activities_page,
        _require_logged_in,
        _safe_exc,
        _wait_activity_search_results,
    )

    activity_id = str(activity_id or "").strip()
    if not activity_id:
        return {
            "status": "failed",
            "step": "validate_activity_id",
            "error": "activity_id 不能为空",
            "activity_id": activity_id,
        }

    try:
        if session_err := _require_logged_in(page, account, account_id):
            return {**session_err, "activity_id": activity_id}

        _install_multi_quick_tab_blocker(page, account_id)
        if not _open_marketing_activities_page(page, account_id, account=account):
            return {
                "status": "failed",
                "step": "open_marketing_activities",
                "error": "未能打开营销活动页或会话已跳转登录",
                "activity_id": activity_id,
                "current_url": page.url,
            }

        page_prepare = prepare_marketing_activities_page_after_open(page, account_id, wait_timeout=20)
        _search_log(
            account_id,
            "就绪",
            "打开后页面守卫",
            ready=page_prepare.get("ready"),
            url=page_prepare.get("wait", {}).get("current_url"),
        )

        phone_popup = dismiss_marketing_phone_popup_safe(page, account_id)
        ensure_marketing_activities_tab_focus(page, account_id)

        wait_result = wait_for_activity_search_input(page, account_id, timeout=12)
        search_input = wait_result.get("search_input") if isinstance(wait_result.get("search_input"), dict) else {}
        if not search_input.get("found"):
            search_input = _find_activity_search_input(page)

        if not search_input.get("found"):
            _search_log(
                account_id,
                "失败",
                "仍未找到活动搜索框",
                url=str(getattr(page, "url", "") or ""),
                wait=wait_result,
                prepare=page_prepare,
            )
            return {
                "status": "failed",
                "step": "find_search_input",
                "error": "未找到活动名称/ID 搜索框",
                "activity_id": activity_id,
                "current_url": page.url,
                "search_input": search_input,
                "page_guard": page_prepare,
                "wait_search_input": wait_result,
                "phone_popup": phone_popup,
                "guarded": True,
            }

        fill_result = _fill_activity_search_input(page, activity_id)
        if not fill_result.get("filled"):
            return {
                "status": "failed",
                "step": "fill_search_input",
                "error": "未能填入活动 ID",
                "activity_id": activity_id,
                "current_url": page.url,
                "fill_result": fill_result,
                "guarded": True,
            }

        phone_popup_after_fill = dismiss_marketing_phone_popup_safe(page, account_id)
        ensure_marketing_activities_tab_focus(page, account_id)

        click_result = _click_activity_search_button(page)
        if not click_result.get("clicked"):
            if not _click_text(page, "查询", timeout=3):
                return {
                    "status": "failed",
                    "step": "click_search_button",
                    "error": "未找到或无法点击查询按钮",
                    "activity_id": activity_id,
                    "current_url": page.url,
                    "click_result": click_result,
                    "guarded": True,
                }
            click_result = {"clicked": True, "text": "查询", "fallback": "text_click"}

        time.sleep(2)
        _dismiss_message_popup(page)
        phone_popup_after_search = dismiss_marketing_phone_popup_safe(page, account_id, max_attempts=6)
        ensure_marketing_activities_tab_focus(page, account_id)
        results = _wait_activity_search_results(page, activity_id, timeout=12)

        if not results.get("matched"):
            return {
                "status": "failed",
                "step": "verify_search_results",
                "error": f"查询后未找到活动 ID {activity_id}",
                "activity_id": activity_id,
                "current_url": page.url,
                "search_input": search_input,
                "fill_result": fill_result,
                "click_result": click_result,
                "results": results,
                "guarded": True,
            }

        _close_multi_quick_channel_tabs(page, account_id)

        print(
            f"[{account_id}] 营销活动搜索成功(守卫): id={activity_id} title={results.get('title', '')}",
            flush=True,
        )
        return {
            "status": "success",
            "step": "search_completed",
            "activity_id": activity_id,
            "current_url": page.url,
            "search_input": search_input,
            "fill_result": fill_result,
            "click_result": click_result,
            "phone_popup": phone_popup,
            "phone_popup_after_fill": phone_popup_after_fill,
            "phone_popup_after_search": phone_popup_after_search,
            "results": results,
            "page_guard": page_prepare,
            "guarded": True,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "step": "search_marketing_activity_guarded",
            "error": _safe_exc(exc),
            "activity_id": activity_id,
            "current_url": getattr(page, "url", ""),
            "guarded": True,
        }

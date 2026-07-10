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
from pdd_agent.skills.campaign.marketing_activity_blocking_modal_dismiss import (
    ensure_marketing_blocking_modals_cleared,
)
from pdd_agent.skills.campaign.marketing_activity_pending_section_guard import (
    dismiss_unexpected_pending_modals,
    prepare_marketing_registration_surface,
)
from pdd_agent.skills.campaign.marketing_activity_phone_popup_safe import dismiss_marketing_phone_popup_safe
from pdd_agent.skills.campaign.marketing_activity_search_input_scope import (
    click_activity_search_button_scoped,
    fill_activity_search_input_scoped,
    find_activity_search_input_scoped,
)

logger = get_logger(__name__)


def _brief(value: Any, *, limit: int = 240) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _search_log(account_id: str, step: str, message: str, **extra: Any) -> None:
    prefix = f"[{account_id}] [营销活动搜索守卫][{step}]"
    parts = [f"{key}={value}" for key, value in extra.items() if value is not None and value != ""]
    line = f"{prefix} {message}"
    if parts:
        line = f"{line} | {' '.join(parts)}"
    logger.info(line)
    print(line, flush=True)


def _log_step_result(
    account_id: str,
    step: str,
    result: dict[str, Any] | None,
    *,
    ok_key: str = "found",
    ok_values: tuple[Any, ...] = (True,),
) -> bool:
    data = result if isinstance(result, dict) else {}
    ok = data.get(ok_key) in ok_values
    _search_log(
        account_id,
        step,
        "成功" if ok else "失败",
        status=data.get("status"),
        step_name=data.get("step"),
        reason=data.get("reason") or data.get("error"),
        method=data.get("method"),
        placeholder=data.get("placeholder"),
        value=data.get("value"),
        section_score=data.get("section_score"),
        detail=_brief({k: v for k, v in data.items() if k not in {"status", "step", "error", "reason"}}),
    )
    return ok


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
    from pdd_agent.skills.campaign.limited_time import _dismiss_message_popup
    from pdd_agent.skills.campaign.marketing_activities import (
        _close_multi_quick_channel_tabs,
        _install_multi_quick_tab_blocker,
        _open_marketing_activities_page,
        _require_logged_in,
        _safe_exc,
        _wait_activity_search_results,
    )

    activity_id = str(activity_id or "").strip()
    _search_log(account_id, "开始", "营销活动搜索守卫启动", activity_id=activity_id, url=getattr(page, "url", ""))
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
        _log_step_result(account_id, "电话浮层", {"dismissed": phone_popup.get("dismissed")}, ok_key="dismissed", ok_values=(True, False))
        blocking_modal = ensure_marketing_blocking_modals_cleared(page, account_id)
        _search_log(
            account_id,
            "遮挡弹窗",
            "清理完成",
            cleared=blocking_modal.get("cleared"),
            dismissed=blocking_modal.get("dismissed"),
        )
        pending_surface = prepare_marketing_registration_surface(page, account_id)
        _search_log(
            account_id,
            "待报名区准备",
            "完成",
            ready=pending_surface.get("ready"),
            unchecked=pending_surface.get("unchecked", {}).get("unchecked"),
            scroll=pending_surface.get("scroll", {}).get("scrolled"),
        )
        ensure_marketing_activities_tab_focus(page, account_id)

        _search_log(account_id, "等待搜索框", "开始轮询", timeout=12, url=getattr(page, "url", ""))
        wait_result = wait_for_activity_search_input(page, account_id, timeout=12)
        _search_log(
            account_id,
            "等待搜索框",
            "轮询结束",
            found=wait_result.get("found"),
            ready=wait_result.get("ready"),
            tick=wait_result.get("tick"),
            reason=wait_result.get("reason"),
            loading=wait_result.get("loading"),
        )
        search_input = wait_result.get("search_input") if isinstance(wait_result.get("search_input"), dict) else {}
        if not search_input.get("found"):
            search_input = find_activity_search_input_scoped(page)
        _log_step_result(account_id, "定位搜索框", search_input)

        blocking_modal_retry: dict[str, Any] | None = None
        pending_surface_retry: dict[str, Any] | None = None
        if not search_input.get("found"):
            blocking_modal_retry = ensure_marketing_blocking_modals_cleared(page, account_id)
            pending_surface_retry = prepare_marketing_registration_surface(page, account_id)
            ensure_marketing_activities_tab_focus(page, account_id)
            search_input = find_activity_search_input_scoped(page)
            _log_step_result(account_id, "重试定位搜索框", search_input)

        if not search_input.get("found"):
            _search_log(
                account_id,
                "失败",
                "仍未找到活动搜索框，搜索守卫结束",
                url=str(getattr(page, "url", "") or ""),
                wait=_brief(wait_result),
                prepare=_brief(page_prepare),
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
                "blocking_modal": blocking_modal,
                "blocking_modal_retry": blocking_modal_retry,
                "pending_surface": pending_surface,
                "pending_surface_retry": pending_surface_retry,
                "guarded": True,
            }

        prepare_marketing_registration_surface(page, account_id)
        _search_log(account_id, "填入活动ID", "开始", activity_id=activity_id)
        fill_result = fill_activity_search_input_scoped(page, activity_id)
        if not _log_step_result(account_id, "填入活动ID", fill_result, ok_key="filled", ok_values=(True,)):
            _search_log(account_id, "失败", "未能填入活动 ID，搜索守卫结束", detail=_brief(fill_result))
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
        prepare_marketing_registration_surface(page, account_id)
        ensure_marketing_activities_tab_focus(page, account_id)

        _search_log(account_id, "点击查询", "开始", activity_id=activity_id, url=getattr(page, "url", ""))
        click_result = click_activity_search_button_scoped(page)
        if not _log_step_result(account_id, "点击查询", click_result, ok_key="clicked", ok_values=(True,)):
            _search_log(account_id, "失败", "未能点击营销活动报名区查询按钮，搜索守卫结束", detail=_brief(click_result))
            return {
                "status": "failed",
                "step": "click_search_button",
                "error": "未找到或无法点击营销活动报名区的查询按钮",
                "activity_id": activity_id,
                "current_url": page.url,
                "click_result": click_result,
                "guarded": True,
            }

        time.sleep(2)
        dismiss_unexpected_pending_modals(page, account_id)
        _dismiss_message_popup(page)
        phone_popup_after_search = dismiss_marketing_phone_popup_safe(page, account_id, max_attempts=6)
        ensure_marketing_activities_tab_focus(page, account_id)
        results = _wait_activity_search_results(page, activity_id, timeout=12)
        if not _log_step_result(account_id, "校验搜索结果", results, ok_key="matched", ok_values=(True,)):
            _search_log(
                account_id,
                "失败",
                f"查询后未找到活动 ID {activity_id}，搜索守卫结束",
                detail=_brief(results),
            )
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

        _search_log(
            account_id,
            "成功",
            "营销活动搜索守卫完成",
            activity_id=activity_id,
            title=results.get("title", ""),
            url=getattr(page, "url", ""),
        )
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
            "pending_surface": pending_surface,
            "guarded": True,
        }
    except Exception as exc:
        _search_log(account_id, "异常", "搜索守卫异常退出", error=_safe_exc(exc), url=getattr(page, "url", ""))
        logger.exception("[%s] search_marketing_activity_guarded failed", account_id)
        return {
            "status": "failed",
            "step": "search_marketing_activity_guarded",
            "error": _safe_exc(exc),
            "activity_id": activity_id,
            "current_url": getattr(page, "url", ""),
            "guarded": True,
        }

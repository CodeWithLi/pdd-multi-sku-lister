"""分支 C 三级列选器 + 关键词搜索选类（与 A/B、弹窗逻辑隔离）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def branch_c_has_category_search_input(page: DpPage) -> bool:
    return bool(page.ele('css:input[placeholder="请输入关键词搜索分类"]', timeout=0.5))


def branch_c_read_submit_state(page: DpPage) -> dict[str, Any]:
    from pdd_agent.skills.listing import upload as listing_upload

    return listing_upload._read_category_submit_state(page)


def branch_c_category_path_ready(page: DpPage) -> bool:
    from pdd_agent.skills.listing import upload as listing_upload

    if listing_upload._branch_c_category_already_selected(page):
        return True
    state = branch_c_read_submit_state(page)
    return bool(state.get("selectedPathReady"))


def branch_c_needs_keyword_category_pick(page: DpPage) -> bool:
    """
    分支 C：出现分类搜索框但尚未选中完整三级路径。
    典型 UI：三列类目树 + 底部「下一步」已显示但点不动。
    """
    from pdd_agent.skills.listing.category_branch_c_modal import (
        is_modal_blocking_category_advance,
    )
    from pdd_agent.skills.listing import upload as listing_upload

    if is_modal_blocking_category_advance(page):
        return False
    if listing_upload._branch_c_category_already_selected(page):
        return False
    if not branch_c_has_category_search_input(page):
        return False
    if branch_c_category_path_ready(page):
        return False

    state = branch_c_read_submit_state(page)
    if state.get("blocking"):
        return True
    if state.get("visible") and not state.get("selectedPathReady"):
        return True
    return True


def run_branch_c_keyword_category_pick(
    page: DpPage,
    account_id: str,
    label: str,
    category_keyword: str,
    *,
    max_wait: int = 20,
) -> bool:
    """
    多步选类：搜索关键词 → 点首条结果 → 确认三级列 → 等待路径就绪。
    """
    from pdd_agent.skills.listing import upload as listing_upload

    keyword = str(category_keyword or "笔袋").strip() or "笔袋"
    _log(account_id, label, f"分支 C 选类 Step1/3：搜索分类「{keyword}」")
    if not listing_upload._select_category_by_keyword_search(
        page,
        account_id,
        label,
        keyword,
    ):
        _log(account_id, label, f"分支 C 选类失败：搜索无结果「{keyword}」")
        return False

    time.sleep(0.8)
    _log(account_id, label, "分支 C 选类 Step2/3：确认三级列选中项")
    listing_upload._confirm_category_picker_selection(page, account_id, label)
    listing_upload._dismiss_category_search_overlay(page, account_id, label)
    time.sleep(0.6)

    _log(account_id, label, "分支 C 选类 Step3/3：等待「已选分类」三级路径就绪")
    for sec in range(max_wait):
        if branch_c_category_path_ready(page):
            _log(account_id, label, f"分支 C 选类完成：三级路径已就绪 ({sec + 1}s)")
            return True
        listing_upload._confirm_category_picker_selection(page, account_id, label)
        listing_upload._dismiss_category_search_overlay(page, account_id, label)
        if (sec + 1) % 5 == 0:
            state = branch_c_read_submit_state(page)
            _log(
                account_id,
                label,
                "分支 C 选类等待中："
                f"selectedPath={bool(state.get('selectedPathReady'))} "
                f"blocking={bool(state.get('blocking'))} ({sec + 1}/{max_wait}s)",
            )
        time.sleep(1)

    ready = branch_c_category_path_ready(page)
    if not ready:
        _log(account_id, label, "分支 C 选类超时：仍未检测到完整三级类目路径")
    return ready


def prepare_branch_c_category_before_next(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    category_mode: str,
    burst_demo: bool = True,
) -> None:
    """分支 C 点下一步前准备：未选完整路径时不因按钮可见而跳过等待。"""
    from pdd_agent.skills.listing.category_page_flow import wait_category_section_ready
    from pdd_agent.skills.listing import upload as listing_upload

    if category_mode == "direct_next":
        _log(account_id, label, "分类页直通模式：已识别为可直接点击下一步")
        listing_upload._dismiss_category_search_overlay(page, account_id, label)
        return

    if category_mode == "manual_picker":
        listing_upload._confirm_category_picker_selection(page, account_id, label)
        listing_upload._dismiss_category_search_overlay(page, account_id, label)
        return

    submit_state = branch_c_read_submit_state(page)
    path_ready = branch_c_category_path_ready(page)
    if path_ready and submit_state.get("visible") and not submit_state.get("disabled"):
        _log(account_id, label, "分支 C：三级类目已就绪，跳过渲染等待")
        listing_upload._dismiss_category_search_overlay(page, account_id, label)
        return

    if submit_state.get("visible") and not path_ready:
        _log(account_id, label, "分支 C：「下一步」可见但类目未选完整，不跳过选类等待")

    if burst_demo:
        _log(account_id, label, "分类页 workaround：随机等待分类渲染")
    wait_category_section_ready(page, account_id, label, burst_demo=burst_demo)
    listing_upload._click_category_section_blank(page)
    listing_upload._dismiss_category_search_overlay(page, account_id, label)
    if burst_demo:
        _log(account_id, label, "分类页 workaround：已点击空白失焦，准备点推荐类目")


def log_branch_c_picker_diagnostics(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    state = branch_c_read_submit_state(page)
    info = {
        "search_input": branch_c_has_category_search_input(page),
        "path_ready": branch_c_category_path_ready(page),
        "needs_keyword_pick": branch_c_needs_keyword_category_pick(page),
        "selectedPathReady": bool(state.get("selectedPathReady")),
        "blocking": bool(state.get("blocking")),
        "submit_visible": bool(state.get("visible")),
        "submit_disabled": bool(state.get("disabled")),
    }
    _log(
        account_id,
        label,
        "分支 C 列选器诊断："
        f"search={info['search_input']} path_ready={info['path_ready']} "
        f"needs_pick={info['needs_keyword_pick']} selectedPath={info['selectedPathReady']} "
        f"blocking={info['blocking']} submit={info['submit_visible']}",
    )
    return info

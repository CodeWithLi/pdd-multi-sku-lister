"""分支 C 分类页选类 + 点下一步（与 A/B 隔离，含诊断日志）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pdd_agent.skills.listing.category_branch_c_modal import (
    ensure_branch_c_recommendation_modal_cleared,
    is_modal_blocking_category_advance,
    log_modal_diagnostics,
)
from pdd_agent.skills.listing.category_branch_c_picker import (
    branch_c_category_path_ready,
    branch_c_needs_keyword_category_pick,
    log_branch_c_picker_diagnostics,
    prepare_branch_c_category_before_next,
    run_branch_c_keyword_category_pick,
)
from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
    ensure_branch_c_category_ready_for_ai_title_flow,
)
from pdd_agent.skills.listing.category_branch_c_recent import (
    log_branch_c_recent_diagnostics,
)
from pdd_agent.skills.listing.category_branch_c_titled_picker import (
    log_branch_c_titled_picker_diagnostics,
)

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

CategoryNextErr = Literal["", "not_found", "no_advance", "modal_blocking"]


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def log_branch_c_category_diagnostics(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    """输出分支 C 分类页当前状态，便于排查未点下一步。"""
    from pdd_agent.skills.listing import upload as listing_upload

    body = listing_upload._category_page_body_text(page)
    body_compact = body.replace("\n", " ")[:240]
    modal_open = listing_upload._is_image_category_recommendation_modal_visible(page)
    if not modal_open:
        modal_open = is_modal_blocking_category_advance(page)
    already_selected = listing_upload._branch_c_category_already_selected(page)
    direct_ready = listing_upload._category_direct_next_ready(page)
    manual_needed = listing_upload._category_page_needs_manual_selection(page)
    submit_state = listing_upload._read_category_submit_state(page)
    info = {
        "modal_open": modal_open,
        "already_selected": already_selected,
        "direct_next_ready": direct_ready,
        "manual_needed": manual_needed,
        "submit_ready": bool(submit_state.get("ready")),
        "submit_blocking": bool(submit_state.get("blocking")),
        "submit_visible": bool(submit_state.get("visible")),
        "submit_disabled": bool(submit_state.get("disabled")),
        "selected_path_ready": bool(submit_state.get("selectedPathReady")),
        "body_preview": body_compact,
    }
    _log(
        account_id,
        label,
        "分支 C 分类页诊断："
        f"modal={modal_open} selected={already_selected} direct={direct_ready} "
        f"manual={manual_needed} submit_ready={info['submit_ready']} "
        f"selectedPath={info['selected_path_ready']} "
        f"blocking={info['submit_blocking']} visible={info['submit_visible']} "
        f"disabled={info['submit_disabled']}",
    )
    if body_compact:
        _log(account_id, label, f"分支 C 分类页文本摘要：{body_compact}")
    return info


def run_branch_c_category_after_covers(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any],
    *,
    category_next_burst_demo: bool = True,
) -> tuple[bool, CategoryNextErr, str]:
    """
    主图上传完成后的分支 C 分类流程：弹窗 → 选类模式 → 点下一步。
    返回 (成功, 错误码, category_mode)。
    """
    from pdd_agent.skills.listing.category_page_flow import (
        click_category_next_and_advance,
        prepare_category_before_next,
    )
    from pdd_agent.skills.listing import upload as listing_upload

    ensure_branch_c_recommendation_modal_cleared(
        page,
        account_id,
        label,
        wait_seconds=10,
    )
    log_modal_diagnostics(page, account_id, label)
    log_branch_c_recent_diagnostics(page, account_id, label)
    log_branch_c_titled_picker_diagnostics(page, account_id, label, listing_info)
    log_branch_c_category_diagnostics(page, account_id, label)
    log_branch_c_picker_diagnostics(page, account_id, label)

    if is_modal_blocking_category_advance(page):
        _log(account_id, label, "分支 C：推荐分类弹窗未关闭，无法点下一步")
        log_modal_diagnostics(page, account_id, label)
        return False, "modal_blocking", "render_wait"

    keyword = str(
        listing_info.get("category_keyword")
        or listing_info.get("category")
        or "笔袋"
    ).strip() or "笔袋"

    from pdd_agent.skills.listing.category_branch_c_page_ai_title_retry import (
        ensure_branch_c_page_ai_title_before_category,
    )

    ensure_branch_c_page_ai_title_before_category(
        page,
        account_id,
        listing_info,
        listing_info,
        label=label,
    )

    if not ensure_branch_c_category_ready_for_ai_title_flow(
        page, account_id, label, listing_info, keyword
    ):
        _log(account_id, label, "分支 C：选类未完成（最近使用/关键词均失败）")
        return False, "not_found", "manual_picker"
    log_branch_c_recent_diagnostics(page, account_id, label)
    log_branch_c_picker_diagnostics(page, account_id, label)

    manual_category = listing_upload._category_page_needs_manual_selection(page)
    category_mode = listing_upload._resolve_category_page_mode(
        page, "C", manual_category=manual_category
    )
    if branch_c_category_path_ready(page) and category_mode == "render_wait":
        manual_category = listing_upload._category_page_needs_manual_selection(page)
        category_mode = listing_upload._resolve_category_page_mode(
            page, "C", manual_category=manual_category
        )
        _log(account_id, label, f"分支 C：选类后重新判定模式 → {category_mode}")
    _log(account_id, label, f"分支 C 分类模式判定：{category_mode}（manual={manual_category}）")

    if listing_upload._branch_c_category_already_selected(page) and category_mode == "direct_next":
        _log(account_id, label, "分支 C：类目已选且可直通，准备点击「下一步」")
    elif listing_upload._branch_c_category_already_selected(page) and category_mode == "render_wait":
        _log(account_id, label, "分支 C：类目已选，等待渲染后点「下一步」")
    elif manual_category:
        from pdd_agent.skills.listing.category_branch_c_titled_picker import (
            branch_c_needs_titled_manual_category_pick,
            run_branch_c_titled_manual_category_pick,
        )

        if branch_c_needs_titled_manual_category_pick(page, listing_info):
            _log(account_id, label, "分支 C-带标题：选择分类 → 最近使用 → 确认")
            if run_branch_c_titled_manual_category_pick(
                page,
                account_id,
                label,
                listing_info,
            ):
                category_mode = "manual_picker"
                _log(account_id, label, "分支 C-带标题：选类完成，准备点下一步")
            else:
                _log(account_id, label, "分支 C-带标题：选类失败")
                return False, "not_found", category_mode
        else:
            _log(account_id, label, "分支 C-手动：打开选择分类并搜索")
            prepare_category_before_next(
                page,
                account_id,
                label,
                mode="render_wait",
                burst_demo=False,
            )
            if not listing_upload._open_category_selector_panel(page):
                _log(account_id, label, "分支 C-手动：未找到「选择分类」入口")
                return False, "not_found", category_mode
            if not listing_upload._select_category_by_keyword_search(
                page,
                account_id,
                label,
                keyword,
            ):
                _log(account_id, label, "分支 C-手动：分类搜索失败")
                return False, "not_found", "manual_picker"
            category_mode = "manual_picker"
            _log(account_id, label, "分支 C-手动：分类搜索完成，mode=manual_picker")
    else:
        prepare_branch_c_category_before_next(
            page,
            account_id,
            label,
            category_mode=category_mode,
            burst_demo=category_next_burst_demo,
        )

    log_branch_c_category_diagnostics(page, account_id, label)
    _log(account_id, label, f"分支 C：开始点击「下一步」（mode={category_mode}）")

    if is_modal_blocking_category_advance(page):
        ensure_branch_c_recommendation_modal_cleared(page, account_id, label, wait_seconds=0)

    from pdd_agent.skills.listing.category_branch_c_next import log_branch_c_next_diagnostics
    from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
        click_branch_c_category_next_with_ai_burst,
    )

    log_branch_c_next_diagnostics(page, account_id, label)

    next_ok, next_err = click_branch_c_category_next_with_ai_burst(
        page,
        account_id,
        label,
        listing_info,
        category_mode=category_mode,
        category_next_burst_demo=category_next_burst_demo,
    )
    if next_ok:
        _log(account_id, label, "分支 C：已点击「下一步」并进入详情页")
    else:
        if next_err == "no_advance":
            if not branch_c_category_path_ready(page):
                _log(account_id, label, "分支 C：未跳转且类目未就绪，重试关键词选类")
                if run_branch_c_keyword_category_pick(
                    page,
                    account_id,
                    label,
                    keyword,
                ):
                    next_ok, next_err = click_branch_c_category_next_with_ai_burst(
                        page,
                        account_id,
                        label,
                        listing_info,
                        category_mode="manual_picker",
                        category_next_burst_demo=False,
                    )
            elif ensure_branch_c_recommendation_modal_cleared(
                page, account_id, label, wait_seconds=2
            ):
                _log(account_id, label, "分支 C：弹窗已确认，重试点击「下一步」")
                next_ok, next_err = click_branch_c_category_next_with_ai_burst(
                    page,
                    account_id,
                    label,
                    listing_info,
                    category_mode=category_mode,
                    category_next_burst_demo=category_next_burst_demo,
                )
        if next_ok:
            _log(account_id, label, "分支 C：重试后已进入详情页")
        else:
            _log(account_id, label, f"分支 C：点击「下一步」失败 err={next_err or 'unknown'}")
            log_branch_c_category_diagnostics(page, account_id, label)
            log_modal_diagnostics(page, account_id, label)
    return next_ok, next_err, category_mode

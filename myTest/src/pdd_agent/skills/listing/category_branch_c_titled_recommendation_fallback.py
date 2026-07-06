"""
分支 C + page_ai 带标题 — 空白点击后推荐类目卡片迟渲染兜底。

场景：简化发布页（主图+标题已填）在 prepare 空白点击后才出现推荐类目卡片，
页面上没有「选择分类」入口，原「关键词搜索选类」路径会误报失败。

仅作兜底：编排层在「打开选择分类」失败后才调用；传统分支 C、不带标题、
已有「选择分类」按钮的路径不受影响。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

DEFAULT_TITLED_RECOMMENDATION_FALLBACK_WAIT = 8


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def is_branch_c_titled_recommendation_fallback_eligible(
    page: DpPage,
    listing_info: dict[str, Any] | None,
) -> bool:
    """仅 page_ai + 已填标题 + 简化发布页（非传统三列 onPage）。"""
    from pdd_agent.skills.listing.category_branch_c_page_ai_title_retry import (
        is_branch_c_page_ai_title_listing,
    )
    from pdd_agent.skills.listing.category_branch_c_recent import (
        read_branch_c_category_selection_state,
    )
    from pdd_agent.skills.listing.category_branch_c_titled_picker import (
        branch_c_has_filled_title,
        read_branch_c_titled_manual_state,
    )

    if not is_branch_c_page_ai_title_listing(listing_info):
        return False
    if not branch_c_has_filled_title(page, listing_info):
        return False

    sel = read_branch_c_category_selection_state(page)
    if sel.get("onPage"):
        return False

    titled = read_branch_c_titled_manual_state(page)
    if not titled.get("hasPublishForm"):
        return False
    if titled.get("searchOnMain"):
        return False
    return True


def branch_c_titled_simplified_category_ready(page: DpPage) -> bool:
    """
    简化页推荐卡片形态：类目已选完整（含平台自动勾选推荐卡片）。
    不用 branch_c_category_path_ready_strict（其依赖 onPage，简化页恒为 False）。
    """
    from pdd_agent.skills.listing import upload as listing_upload
    from pdd_agent.skills.listing.category_branch_c_modal import (
        is_modal_blocking_category_advance,
    )

    if is_modal_blocking_category_advance(page):
        return False
    state = listing_upload._read_category_submit_state(page)
    if state.get("blocking"):
        return False
    return bool(state.get("selectedPathReady"))


def _has_titled_recommendation_cards(page: DpPage) -> bool:
    from pdd_agent.skills.listing import upload as listing_upload

    if not listing_upload._category_section_is_ready(page):
        return False
    titled = read_branch_c_titled_manual_state_safe(page)
    if titled.get("noRecommendation"):
        return False
    if titled.get("selectButtonVisible"):
        return False
    return True


def read_branch_c_titled_manual_state_safe(page: DpPage) -> dict[str, Any]:
    from pdd_agent.skills.listing.category_branch_c_titled_picker import (
        read_branch_c_titled_manual_state,
    )

    try:
        raw = read_branch_c_titled_manual_state(page)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def try_recover_branch_c_titled_category_after_render_nudge(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any] | None,
    *,
    max_wait: int = DEFAULT_TITLED_RECOMMENDATION_FALLBACK_WAIT,
) -> bool:
    """
    兜底：空白点击后等待推荐卡片出现；已选则直接成功，未选则点首条推荐卡片。

    返回 True 表示简化页类目已就绪，可继续点「下一步」。
    """
    if not is_branch_c_titled_recommendation_fallback_eligible(page, listing_info):
        return False

    _log(account_id, label, "分支 C 带标题兜底：检测迟渲染的推荐类目卡片…")

    for sec in range(max(max_wait, 1)):
        if branch_c_titled_simplified_category_ready(page):
            _log(account_id, label, "分支 C 带标题兜底：推荐类目已选中，跳过关键词搜索")
            return True

        if _has_titled_recommendation_cards(page):
            from pdd_agent.skills.listing import upload as listing_upload

            _log(
                account_id,
                label,
                "分支 C 带标题兜底：发现推荐类目卡片，尝试点击首条",
            )
            listing_upload._click_branch_c_category_recommendation(
                page, account_id, label
            )
            time.sleep(0.8)
            if branch_c_titled_simplified_category_ready(page):
                _log(account_id, label, "分支 C 带标题兜底：点击推荐卡片后类目已就绪")
                return True

        if sec + 1 < max_wait:
            time.sleep(1)
            if (sec + 1) % 3 == 0:
                _log(
                    account_id,
                    label,
                    f"分支 C 带标题兜底：仍在等待推荐卡片… ({sec + 1}/{max_wait}s)",
                )

    ready = branch_c_titled_simplified_category_ready(page)
    if not ready:
        _log(account_id, label, "分支 C 带标题兜底：未能确认推荐类目就绪")
    return ready

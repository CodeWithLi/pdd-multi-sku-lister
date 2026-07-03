"""
分支 C 分类页形态分类器 — 统一判定 TRADITIONAL / SIMPLIFIED_* 互斥 variant。

形态说明：
- TRADITIONAL：传统选类页（onPage=True，含搜索框/第2步选类）
- SIMPLIFIED_AUTO：形态 B 且类目已就绪，可跳过选类直接点下一步
- SIMPLIFIED_MANUAL：形态 B 且需手动选类（带标题选类器或关键词搜索）
- SIMPLIFIED_PENDING：形态 B 但分类区尚未渲染，不可当作 AUTO 跳过
- UNKNOWN：无法判定，由编排层回退传统选类逻辑
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

META_KEY_PAGE_VARIANT = "_branch_c_page_variant"


class BranchCPageVariant(str, Enum):
    TRADITIONAL = "traditional"
    SIMPLIFIED_AUTO = "simplified_auto"
    SIMPLIFIED_MANUAL = "simplified_manual"
    SIMPLIFIED_PENDING = "simplified_pending"
    UNKNOWN = "unknown"


def branch_c_is_simplified_ai_title_context(
    page: DpPage,
    listing_info: dict[str, Any] | None,
) -> bool:
    """
    形态 B 上下文：主图 + 标题已填的简化发布页。
    不含「是否可跳过选类」判断（与 branch_c_is_simplified_ai_title_publish_page 区分）。
    """
    from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
        branch_c_category_page_ai_title_applied,
        branch_c_category_page_ai_title_visible,
        _listing_uses_page_ai_title_mode,
    )
    from pdd_agent.skills.listing.category_branch_c_recent import (
        read_branch_c_category_selection_state,
    )
    from pdd_agent.skills.listing.page_ai_title import _read_title_from_input

    state = read_branch_c_category_selection_state(page)
    if state.get("onPage"):
        return False

    title = str(_read_title_from_input(page) or "").strip()
    if len(title) < 2:
        return False

    ai_evidence = (
        branch_c_category_page_ai_title_applied(listing_info)
        or branch_c_category_page_ai_title_visible(page)
        or _listing_uses_page_ai_title_mode(listing_info)
    )
    if not ai_evidence:
        return False

    try:
        has_publish_form = bool(
            page.run_js(
                """
                const t = document.body.innerText || '';
                return t.includes('商品主图') && t.includes('商品标题');
                """
            )
        )
        return has_publish_form
    except Exception:
        return False


def classify_branch_c_page_variant(
    page: DpPage,
    listing_info: dict[str, Any] | None,
) -> BranchCPageVariant:
    """
    单一入口判定分支 C 当前页面形态（互斥）。

    关键规则：SIMPLIFIED_AUTO 仅在类目 path_ready 时返回，避免未选类时误跳过。
    """
    from pdd_agent.skills.listing import upload as listing_upload
    from pdd_agent.skills.listing.category_branch_c_recent import (
        branch_c_category_path_ready_strict,
        read_branch_c_category_selection_state,
    )
    from pdd_agent.skills.listing.category_branch_c_titled_picker import (
        branch_c_needs_titled_manual_category_pick,
        read_branch_c_titled_manual_state,
    )

    state = read_branch_c_category_selection_state(page)
    on_page = bool(state.get("onPage"))
    path_ready = branch_c_category_path_ready_strict(page)
    simplified_ctx = branch_c_is_simplified_ai_title_context(page, listing_info)

    if on_page:
        return BranchCPageVariant.TRADITIONAL

    if path_ready and simplified_ctx:
        return BranchCPageVariant.SIMPLIFIED_AUTO

    if path_ready:
        return BranchCPageVariant.TRADITIONAL

    if simplified_ctx:
        if branch_c_needs_titled_manual_category_pick(page, listing_info):
            return BranchCPageVariant.SIMPLIFIED_MANUAL

        manual_needed = listing_upload._category_page_needs_manual_selection(page)
        titled_state = read_branch_c_titled_manual_state(page)

        if manual_needed:
            return BranchCPageVariant.SIMPLIFIED_MANUAL

        if state.get("blocking") and (
            titled_state.get("selectButtonVisible") or titled_state.get("modalOpen")
        ):
            return BranchCPageVariant.SIMPLIFIED_MANUAL

        if not listing_upload._category_section_is_ready(page):
            return BranchCPageVariant.SIMPLIFIED_PENDING

        if not titled_state.get("selectButtonVisible") and not manual_needed:
            return BranchCPageVariant.SIMPLIFIED_PENDING

        return BranchCPageVariant.SIMPLIFIED_PENDING

    return BranchCPageVariant.UNKNOWN


def log_branch_c_variant_diagnostics(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any] | None,
) -> BranchCPageVariant:
    """输出形态判定诊断并写入 listing_info meta。"""
    from pdd_agent.skills.listing.category_branch_c_recent import (
        read_branch_c_category_selection_state,
    )
    from pdd_agent.skills.listing.category_branch_c_titled_picker import (
        read_branch_c_titled_manual_state,
    )

    variant = classify_branch_c_page_variant(page, listing_info)
    if isinstance(listing_info, dict):
        listing_info[META_KEY_PAGE_VARIANT] = variant.value

    sel = read_branch_c_category_selection_state(page)
    titled = read_branch_c_titled_manual_state(page)
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(
        f"{prefix} 分支 C 页面形态：{variant.value} "
        f"(on_page={bool(sel.get('onPage'))} path_ready={bool(sel.get('pathReady'))} "
        f"select={bool(titled.get('selectButtonVisible'))} "
        f"manual_hint={bool(titled.get('noRecommendation'))})".strip(),
        flush=True,
    )
    return variant

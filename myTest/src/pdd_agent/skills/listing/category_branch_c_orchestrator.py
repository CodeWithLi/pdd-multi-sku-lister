"""
分支 C 分类选类编排层 — 按页面形态调度互斥 strategy，单一对外入口。

各 strategy 复用现有模块，不在此重复 DOM/点击逻辑。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pdd_agent.skills.listing.category_branch_c_variant import (
    BranchCPageVariant,
    classify_branch_c_page_variant,
    log_branch_c_variant_diagnostics,
)

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def _run_strategy_traditional(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any],
    category_keyword: str,
) -> bool:
    from pdd_agent.skills.listing.category_branch_c_recent import (
        ensure_branch_c_category_selected,
    )

    _log(account_id, label, "分支 C 编排：形态 A 传统选类页")
    return ensure_branch_c_category_selected(
        page,
        account_id,
        label,
        category_keyword,
        listing_info,
    )


def _run_strategy_simplified_auto(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any],
) -> bool:
    from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
        META_KEY_CATEGORY_AI_APPLIED,
    )

    listing_info[META_KEY_CATEGORY_AI_APPLIED] = True
    _log(
        account_id,
        label,
        "分支 C 编排：形态 B-自动，类目已就绪，跳过选类直接点「下一步」",
    )
    return True


def _run_strategy_simplified_manual(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any],
    category_keyword: str,
) -> bool:
    from pdd_agent.skills.listing import upload as listing_upload
    from pdd_agent.skills.listing.category_branch_c_recent import (
        branch_c_category_path_ready_strict,
    )
    from pdd_agent.skills.listing.category_branch_c_titled_picker import (
        branch_c_needs_titled_manual_category_pick,
        run_branch_c_titled_manual_category_pick,
    )
    from pdd_agent.skills.listing.category_page_flow import prepare_category_before_next

    if branch_c_category_path_ready_strict(page):
        return True

    if branch_c_needs_titled_manual_category_pick(page, listing_info):
        _log(account_id, label, "分支 C 编排：形态 B-手动，选择分类 → 最近使用 → 确认")
        if run_branch_c_titled_manual_category_pick(
            page,
            account_id,
            label,
            listing_info,
        ):
            return True
        _log(account_id, label, "分支 C 编排：形态 B-手动带标题选类失败")
        return False

    _log(account_id, label, "分支 C 编排：形态 B-手动，打开选择分类并关键词搜索")
    prepare_category_before_next(
        page,
        account_id,
        label,
        mode="render_wait",
        burst_demo=False,
    )
    if not listing_upload._open_category_selector_panel(page):
        _log(account_id, label, "分支 C 编排：未找到「选择分类」入口")
        return False
    if not listing_upload._select_category_by_keyword_search(
        page,
        account_id,
        label,
        category_keyword,
    ):
        _log(account_id, label, "分支 C 编排：分类关键词搜索失败")
        return False
    return branch_c_category_path_ready_strict(page)


def _wait_simplified_category_render(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_wait: int,
) -> None:
    from pdd_agent.skills.listing import upload as listing_upload

    _log(
        account_id,
        label,
        f"分支 C 编排：形态 B-待渲染，等待商品分类区块（最多 {max_wait}s）",
    )
    listing_upload._wait_for_category_section_ready(
        page,
        account_id,
        label,
        max_wait=max_wait,
    )


def ensure_branch_c_category_selection(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any],
    category_keyword: str,
    *,
    pending_max_wait: int = 45,
) -> tuple[bool, str]:
    """
    分支 C 选类唯一编排入口。

    返回 (选类是否完成, 最终 page variant 值)。
    """
    variant = log_branch_c_variant_diagnostics(page, account_id, label, listing_info)

    if variant == BranchCPageVariant.SIMPLIFIED_PENDING:
        _wait_simplified_category_render(
            page,
            account_id,
            label,
            max_wait=pending_max_wait,
        )
        variant = log_branch_c_variant_diagnostics(page, account_id, label, listing_info)

    if variant == BranchCPageVariant.TRADITIONAL:
        ok = _run_strategy_traditional(
            page, account_id, label, listing_info, category_keyword
        )
        return ok, variant.value

    if variant == BranchCPageVariant.SIMPLIFIED_AUTO:
        ok = _run_strategy_simplified_auto(page, account_id, label, listing_info)
        return ok, variant.value

    if variant == BranchCPageVariant.SIMPLIFIED_MANUAL:
        ok = _run_strategy_simplified_manual(
            page, account_id, label, listing_info, category_keyword
        )
        return ok, variant.value

    if variant == BranchCPageVariant.SIMPLIFIED_PENDING:
        _log(
            account_id,
            label,
            "分支 C 编排：分类区等待后仍为 PENDING，改走手动选类",
        )
        ok = _run_strategy_simplified_manual(
            page, account_id, label, listing_info, category_keyword
        )
        return ok, BranchCPageVariant.SIMPLIFIED_MANUAL.value

    _log(account_id, label, "分支 C 编排：形态 UNKNOWN，回退传统选类")
    ok = _run_strategy_traditional(
        page, account_id, label, listing_info, category_keyword
    )
    return ok, BranchCPageVariant.UNKNOWN.value

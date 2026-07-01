"""
分支 C 分类页 — 上传主图后出现「AI 智能推荐标题 / 立即使用」的兼容处理。

两种分类页形态（互不影响）：
- 形态 A（原逻辑）：分类页无 AI 推荐栏 → 不等待，选类后直接点「下一步」，详情页再填标题。
- 形态 B（本模块）：分类页出现 AI 推荐栏 → 先点「立即使用」，再点「下一步」；未跳转则随机连点。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

CategoryNextErr = Literal["", "not_found", "no_advance", "modal_blocking"]
META_KEY_CATEGORY_AI_APPLIED = "_branch_c_category_ai_title_applied"


def _listing_uses_page_ai_title_mode(listing_info: dict[str, Any] | None) -> bool:
    from pdd_agent.skills.listing.page_ai_title import is_page_ai_title_mode

    return is_page_ai_title_mode(listing_info or {})


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def branch_c_category_page_ai_title_visible(page: DpPage) -> bool:
    """分类页是否出现 AI 推荐标题栏（含「立即使用」/「AI/智能推荐标题」）。"""
    from pdd_agent.skills.listing.category_branch_c_page_ai_title_retry import (
        branch_c_category_page_ai_title_bar_visible,
    )

    return branch_c_category_page_ai_title_bar_visible(page)


def apply_branch_c_category_page_ai_title_when_visible(
    page: DpPage,
    account_id: str,
    product_info: dict,
    resolved_title: str = "",
    *,
    label: str = "",
) -> tuple[str, bool]:
    """
    形态 B：分类页有 AI 推荐栏时点击「立即使用」/「AI生成」填标题。
    返回 (title, applied)；未出现推荐栏或未启用 page_ai 时 applied=False。
    """
    from pdd_agent.skills.listing.page_ai_title import (
        _read_title_from_input,
        is_page_ai_title_mode,
        wait_and_apply_page_ai_title,
    )

    if not is_page_ai_title_mode(product_info):
        return "", False
    if not branch_c_category_page_ai_title_visible(page):
        return "", False

    existing = _read_title_from_input(page)
    if existing:
        _log(account_id, label, f"分支 C 分类页（AI 栏）：标题已存在 → {existing[:60]}")
        return existing, True

    _log(account_id, label, "分支 C 分类页（AI 栏）：检测到「立即使用」，先填标题再点下一步")
    try:
        title = wait_and_apply_page_ai_title(
            page,
            account_id,
            initial_wait=2,
            max_wait=25,
        )
        if title:
            return title, True
    except RuntimeError as exc:
        existing = _read_title_from_input(page)
        if existing:
            _log(account_id, label, f"分支 C 分类页（AI 栏）：超时但标题已填入 → {existing[:60]}")
            return existing, True
        _log(account_id, label, f"分支 C 分类页（AI 栏）：AI 标题失败，继续选类/下一步（{exc}）")

    fallback = str(resolved_title or "").strip()
    return fallback, bool(fallback)


def prepare_branch_c_cover_upload_title(
    page: DpPage,
    account_id: str,
    product_info: dict,
    resolved_title: str = "",
    *,
    label: str = "",
) -> tuple[str, bool]:
    """
    主图上传后标题策略：
    - page_ai：轮询重试「立即使用」（新 retry 模块，避免 AI 栏晚出现漏检）
    - 形态 B：单次检测到 AI 栏即填标题
    - 形态 A：原 apply_title_after_branch_c_cover_upload
    """
    from pdd_agent.skills.listing.page_ai_title import _read_title_from_input

    if _listing_uses_page_ai_title_mode(product_info):
        from pdd_agent.skills.listing.category_branch_c_page_ai_title_retry import (
            retry_apply_branch_c_page_ai_title,
        )

        title, applied = retry_apply_branch_c_page_ai_title(
            page,
            account_id,
            product_info,
            resolved_title,
            label=label,
        )
        if applied:
            return title, True
        title_in_input = str(_read_title_from_input(page) or "").strip()
        if title_in_input:
            return title_in_input, True
        return str(resolved_title or "").strip(), False

    title, applied = apply_branch_c_category_page_ai_title_when_visible(
        page,
        account_id,
        product_info,
        resolved_title,
        label=label,
    )
    if applied:
        return title, True

    from pdd_agent.skills.listing.category_branch_title import (
        apply_title_after_branch_c_cover_upload,
    )

    title = apply_title_after_branch_c_cover_upload(
        page,
        account_id,
        product_info,
        resolved_title,
        label=label,
    )
    return title, False


def branch_c_category_page_ai_title_applied(listing_info: dict[str, Any] | None) -> bool:
    return bool((listing_info or {}).get(META_KEY_CATEGORY_AI_APPLIED))


def branch_c_is_simplified_ai_title_publish_page(
    page: DpPage,
    listing_info: dict[str, Any] | None,
) -> bool:
    """
    形态 B 简化分类页：主图 + AI 标题已填，无「第2步选类 / 最近使用 / 搜索框」。
    与传统 on_page=True 的选类页互斥，此类页面直接点「下一步」。

    判定条件（全部满足）：
    - 非传统选类页（on_page=False 且 path_ready=False）
    - 标题输入框已有内容
    - 有 AI 标题流程证据（meta 标记或页面上仍有 AI 推荐栏）
    - 发布表单特征（商品主图 + 商品标题）
    - 「下一步，完善商品信息」按钮可见且未被「请选择完整分类」阻断
    """
    from pdd_agent.skills.listing.category_branch_c_recent import (
        read_branch_c_category_selection_state,
    )
    from pdd_agent.skills.listing.page_ai_title import _read_title_from_input

    state = read_branch_c_category_selection_state(page)
    if state.get("onPage") or state.get("pathReady"):
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
        if not has_publish_form:
            return False
    except Exception:
        return False

    from pdd_agent.skills.listing import upload as listing_upload

    submit = listing_upload._read_category_submit_state(page)
    if submit.get("blocking"):
        return False
    if not submit.get("visible"):
        return False
    return True


def ensure_branch_c_category_ready_for_ai_title_flow(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any],
    category_keyword: str,
) -> bool:
    """
    分支 C 选类门禁：简化 AI 标题页跳过选类；传统选类页走 ensure_branch_c_category_selected。
    """
    from pdd_agent.skills.listing.category_branch_c_recent import (
        ensure_branch_c_category_selected,
    )

    if branch_c_is_simplified_ai_title_publish_page(page, listing_info):
        listing_info[META_KEY_CATEGORY_AI_APPLIED] = True
        _log(
            account_id,
            label,
            "分支 C 简化页（AI 标题）：无传统选类区，跳过选类直接点「下一步」",
        )
        return True
    return ensure_branch_c_category_selected(page, account_id, label, category_keyword)


def click_branch_c_category_next_with_ai_burst(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any],
    *,
    category_mode: str,
    category_next_burst_demo: bool = True,
) -> tuple[bool, CategoryNextErr]:
    """
    点「下一步」：
    - AI 标题页：选类后未跳转 → 随机页面点击 3–5 次 → 再点下一步（专用 nudge 模块）
    - 形态 A：保持原有 burst 规则
    """
    from pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge import (
        advance_branch_c_category_after_ai_title_selection,
        branch_c_ai_title_nudge_enabled,
    )
    from pdd_agent.skills.listing.category_page_flow import click_category_next_and_advance

    if branch_c_ai_title_nudge_enabled(listing_info, page):
        ok, err = advance_branch_c_category_after_ai_title_selection(
            page,
            account_id,
            label,
            listing_info,
            category_mode=category_mode,
        )
        return ok, err  # type: ignore[return-value]

    return click_category_next_and_advance(
        page,
        account_id,
        label,
        ui_type="C",
        mode=category_mode,  # type: ignore[arg-type]
        burst_demo=category_next_burst_demo and category_mode == "render_wait",
    )

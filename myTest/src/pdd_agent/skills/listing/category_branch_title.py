"""分类页各 UI 分支的标题策略：A/B 需在分类页填标题；C 可先选类点下一步。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def apply_title_after_cover_upload_for_branch(
    page: DpPage,
    account_id: str,
    product_info: dict,
    resolved_title: str = "",
    *,
    ui_type: str = "",
    label: str = "",
    phase: str = "category_page",
) -> str:
    """
    按 UI 分支分发标题逻辑。
    - C + category_page：不阻塞等待 AI，选类后直接下一步
    - A/B 或 details_page：沿用原有 apply_title_after_cover_upload
    """
    branch = str(ui_type or "").strip().upper() or "A"
    if branch == "C" and phase == "category_page":
        return apply_title_after_branch_c_cover_upload(
            page,
            account_id,
            product_info,
            resolved_title,
            label=label,
        )
    from pdd_agent.skills.listing.page_ai_title import apply_title_after_cover_upload

    _log(account_id, label, f"分支 {branch}：{phase} 填标题（沿用 A/B 逻辑）")
    return apply_title_after_cover_upload(page, account_id, product_info, resolved_title)


def apply_title_after_branch_c_cover_upload(
    page: DpPage,
    account_id: str,
    product_info: dict,
    resolved_title: str = "",
    *,
    label: str = "",
) -> str:
    """分支 C 分类页：已有标题则读取；page_ai 不在此等待，避免卡住无法点下一步。"""
    from pdd_agent.skills.listing.page_ai_title import (
        _fill_manual_title,
        _read_title_from_input,
        is_page_ai_title_mode,
    )

    existing = _read_title_from_input(page)
    if existing:
        _log(account_id, label, f"分支 C 分类页：标题已存在，跳过 AI 等待 → {existing[:60]}")
        return existing

    if is_page_ai_title_mode(product_info):
        _log(
            account_id,
            label,
            "分支 C 分类页：page_ai 不在此等待「立即使用」，选类后直接点「下一步」",
        )
        return str(resolved_title or "").strip()

    title = str(resolved_title or "").strip()
    if title and _fill_manual_title(page, account_id, title):
        _log(account_id, label, "分支 C 分类页：已手动填入标题")
        return title
    if title:
        _log(account_id, label, "分支 C 分类页：保留预生成标题，详情页再填")
        return title

    _log(account_id, label, "分支 C 分类页：无标题阻塞，继续选类/下一步")
    return ""


def apply_title_after_branch_c_category_advance(
    page: DpPage,
    account_id: str,
    product_info: dict,
    resolved_title: str = "",
    *,
    label: str = "",
) -> str:
    """分支 C 进入详情页后，再执行 page_ai / 手动标题（与 A/B 行为对齐）。"""
    from pdd_agent.skills.listing.page_ai_title import (
        _read_title_from_input,
        apply_title_after_cover_upload,
        is_page_ai_title_mode,
    )

    existing = _read_title_from_input(page)
    if existing:
        _log(account_id, label, f"分支 C 详情页：标题已存在 → {existing[:60]}")
        return existing

    if is_page_ai_title_mode(product_info):
        _log(account_id, label, "分支 C 详情页：开始 page_ai 标题（「立即使用」/ AI生成）")
        try:
            return apply_title_after_cover_upload(page, account_id, product_info, resolved_title)
        except RuntimeError as exc:
            existing = _read_title_from_input(page)
            if existing:
                _log(account_id, label, f"分支 C 详情页：AI 超时但标题已填入 → {existing[:60]}")
                return existing
            _log(account_id, label, f"分支 C 详情页：page_ai 失败，继续流程（{exc}）")
            return str(resolved_title or "").strip()

    _log(account_id, label, "分支 C 详情页：非 page_ai，走标准填标题")
    return apply_title_after_cover_upload(page, account_id, product_info, resolved_title)

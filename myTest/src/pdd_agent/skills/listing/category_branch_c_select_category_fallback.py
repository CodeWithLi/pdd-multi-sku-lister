"""
分支 C + page_ai 带标题 — 「选择分类 → 最近使用首条 → 确认」兜底。

场景：简化发布页出现「暂无推荐的分类 / 选择分类」，但正式选类路径
（带标题选类器 / 关键词搜索）因 DOM 检测滞后或未命中而失败。

仅作兜底：编排层在正式选类失败后才调用；成功路径不受影响。
内部全程 try/except，失败仅记日志，不抛异常阻断后续流程。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

DEFAULT_SELECT_CATEGORY_FALLBACK_WAIT = 12
RECENT_CLICK_SETTLE_SECONDS = 3


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


_READ_FALLBACK_STATE_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
function cleanPath(t) {
    return (t || '').replace(/\\s+/g, ' ').trim();
}
function isCategoryPath(text) {
    const t = cleanPath(text);
    if (!t.includes('>')) return false;
    const parts = t.split('>').map((p) => p.trim()).filter(Boolean);
    return parts.length >= 3 && t.length >= 12 && t.length <= 180;
}
function isInRecentSection(el) {
    let node = el;
    for (let i = 0; i < 14 && node; i++) {
        const t = (node.innerText || node.textContent || '').slice(0, 200);
        if (t.includes('最近使用')) return true;
        node = node.parentElement;
    }
    return false;
}
function findPickerModal() {
    for (const el of document.querySelectorAll(
        '[data-testid="beast-core-modal"], [class*="beast-core-modal"], [class*="modal"], [class*="Modal"], [role="dialog"], [class*="dialog"], [class*="Dialog"]'
    )) {
        if (!isVisible(el)) continue;
        const t = el.innerText || el.textContent || '';
        if (!t.includes('选择商品分类')) continue;
        return el;
    }
    return null;
}
function findSelectCategoryButton() {
    const modal = findPickerModal();
    const candidates = [];
    for (const el of document.querySelectorAll('button, a, span, div, label')) {
        const raw = (el.innerText || el.textContent || '').trim();
        const compact = norm(raw);
        if (!compact.includes('选择分类')) continue;
        if (compact.length > 24) continue;
        if (modal && modal.contains(el)) continue;
        if (!isVisible(el)) continue;
        const r = el.getBoundingClientRect();
        candidates.push({ el, area: r.width * r.height, top: r.top });
    }
    if (!candidates.length) return null;
    candidates.sort((a, b) => a.area - b.area || a.top - b.top);
    return candidates[0].el;
}
const body = document.body?.innerText || '';
const compact = norm(body);
const modal = findPickerModal();
const selectBtn = findSelectCategoryButton();
const recentPaths = [];
const recentRoot = modal || document.body;
for (const el of recentRoot.querySelectorAll('div, span, a, li, button')) {
    if (!isVisible(el) || !isInRecentSection(el)) continue;
    const t = cleanPath(el.innerText || el.textContent || '');
    if (!isCategoryPath(t) || t.includes('清空')) continue;
    if (!recentPaths.includes(t)) recentPaths.push(t);
}
return {
    modalOpen: !!modal,
    selectButtonVisible: !!selectBtn,
    noRecommendation: compact.includes('暂无推荐的分类')
        || (compact.includes('暂无推荐') && compact.includes('手动选择')),
    hasCategorySection: compact.includes('商品分类'),
    recentPaths,
};
"""

_CLICK_SELECT_CATEGORY_LENIENT_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden';
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
for (const el of document.querySelectorAll('button, a, span, div, label')) {
    const compact = norm((el.innerText || el.textContent || '').trim());
    if (!compact.includes('选择分类') || compact.length > 24) continue;
    if (!isVisible(el)) continue;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    el.click();
    return true;
}
return false;
"""


def read_branch_c_select_category_fallback_state(page: DpPage) -> dict[str, Any]:
    try:
        raw = page.run_js(_READ_FALLBACK_STATE_JS)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _branch_c_fallback_category_ready(page: DpPage) -> bool:
    from pdd_agent.skills.listing.category_branch_c_recent import (
        branch_c_category_path_ready_strict,
    )
    from pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback import (
        branch_c_titled_simplified_category_ready,
    )

    return branch_c_category_path_ready_strict(page) or branch_c_titled_simplified_category_ready(
        page
    )


def is_branch_c_select_category_fallback_eligible(
    page: DpPage,
    listing_info: dict[str, Any] | None,
) -> bool:
    """
    比正式带标题选类器更宽松：有标题 + page_ai + 出现「选择分类/暂无推荐」迹象即可。
    """
    from pdd_agent.skills.listing.category_branch_c_modal import (
        is_image_category_recommendation_modal_visible,
        is_modal_blocking_category_advance,
    )
    from pdd_agent.skills.listing.category_branch_c_page_ai_title_retry import (
        is_branch_c_page_ai_title_listing,
    )
    from pdd_agent.skills.listing.category_branch_c_recent import (
        read_branch_c_category_selection_state,
    )
    from pdd_agent.skills.listing.category_branch_c_titled_picker import (
        branch_c_has_filled_title,
    )

    if not is_branch_c_page_ai_title_listing(listing_info):
        return False
    if not branch_c_has_filled_title(page, listing_info):
        return False
    if _branch_c_fallback_category_ready(page):
        return False
    if is_image_category_recommendation_modal_visible(page):
        return False
    if is_modal_blocking_category_advance(page):
        return False

    sel = read_branch_c_category_selection_state(page)
    if sel.get("onPage") and not sel.get("blocking"):
        return False

    state = read_branch_c_select_category_fallback_state(page)
    if state.get("modalOpen") and state.get("recentPaths"):
        return True
    if state.get("selectButtonVisible"):
        return True
    if state.get("noRecommendation") and state.get("hasCategorySection"):
        return True

    try:
        if page.ele("text:选择分类", timeout=0.3):
            return True
    except Exception:
        pass
    return False


def _nudge_category_section(page: DpPage) -> None:
    from pdd_agent.skills.listing import upload as listing_upload

    try:
        listing_upload._click_category_section_blank(page)
    except Exception:
        pass


def _click_select_category_button(page: DpPage) -> bool:
    from pdd_agent.skills.listing import upload as listing_upload

    try:
        if listing_upload._open_category_selector_panel(page):
            return True
    except Exception:
        pass
    try:
        return bool(page.run_js(_CLICK_SELECT_CATEGORY_LENIENT_JS))
    except Exception:
        return False
    return False


def _click_first_recent_in_modal(page: DpPage) -> tuple[bool, str]:
    from pdd_agent.skills.listing.category_branch_c_titled_picker import (
        branch_c_click_first_recent_in_picker_modal,
    )

    try:
        return branch_c_click_first_recent_in_picker_modal(page)
    except Exception:
        return False, "exception"


def _confirm_picker_modal(page: DpPage) -> bool:
    from pdd_agent.skills.listing.category_branch_c_titled_picker import (
        branch_c_confirm_manual_category_picker_modal,
    )

    try:
        return branch_c_confirm_manual_category_picker_modal(page)
    except Exception:
        return False


def try_branch_c_select_category_recent_fallback(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any] | None,
    *,
    max_wait: int = DEFAULT_SELECT_CATEGORY_FALLBACK_WAIT,
) -> bool:
    """
    兜底：选择分类 → 最近使用首条 → 等 3s → 确认。

    返回 True 表示类目已就绪；False 表示未成功（不抛异常）。
    """
    try:
        if not is_branch_c_select_category_fallback_eligible(page, listing_info):
            return False

        if _branch_c_fallback_category_ready(page):
            _log(account_id, label, "分支 C 选择分类兜底：类目已就绪，跳过")
            return True

        _log(account_id, label, "分支 C 选择分类兜底：尝试「选择分类 → 最近使用 → 确认」")
        _nudge_category_section(page)
        time.sleep(0.5)

        state = read_branch_c_select_category_fallback_state(page)
        _log(
            account_id,
            label,
            "分支 C 选择分类兜底："
            f"select={bool(state.get('selectButtonVisible'))} "
            f"modal={bool(state.get('modalOpen'))} "
            f"recent={len(state.get('recentPaths') or [])}",
        )

        if not state.get("modalOpen"):
            if not state.get("selectButtonVisible"):
                if not _click_select_category_button(page):
                    _log(account_id, label, "分支 C 选择分类兜底：未找到「选择分类」按钮")
                    return False
                _log(account_id, label, "分支 C 选择分类兜底 Step1/3：已点击「选择分类」")
            else:
                _log(account_id, label, "分支 C 选择分类兜底 Step1/3：点击「选择分类」")
                if not _click_select_category_button(page):
                    _log(account_id, label, "分支 C 选择分类兜底：点击「选择分类」失败")
                    return False
            time.sleep(1.2)

        for sec in range(max(max_wait, 1)):
            if _branch_c_fallback_category_ready(page):
                _log(account_id, label, f"分支 C 选择分类兜底：类目已就绪 ({sec + 1}s)")
                return True

            state = read_branch_c_select_category_fallback_state(page)
            if not state.get("modalOpen"):
                if sec >= 2 and state.get("selectButtonVisible"):
                    _click_select_category_button(page)
                time.sleep(0.8)
                continue

            if not state.get("recentPaths"):
                time.sleep(0.8)
                continue

            _log(account_id, label, "分支 C 选择分类兜底 Step2/3：点击「最近使用」首条")
            clicked, picked_text = _click_first_recent_in_modal(page)
            if not clicked:
                _log(
                    account_id,
                    label,
                    f"分支 C 选择分类兜底：最近使用点击失败（{picked_text}）",
                )
                time.sleep(0.8)
                continue
            _log(account_id, label, f"分支 C 选择分类兜底：已选「{picked_text}」")
            time.sleep(RECENT_CLICK_SETTLE_SECONDS)

            _log(account_id, label, "分支 C 选择分类兜底 Step3/3：点击弹窗「确认」")
            if not _confirm_picker_modal(page):
                _log(account_id, label, "分支 C 选择分类兜底：点击「确认」失败，重试…")
                time.sleep(0.8)
                continue

            from pdd_agent.skills.listing import upload as listing_upload

            time.sleep(0.8)
            try:
                listing_upload._dismiss_category_search_overlay(page, account_id, label)
                listing_upload._confirm_category_picker_selection(page, account_id, label)
            except Exception:
                pass

            if _branch_c_fallback_category_ready(page):
                _log(account_id, label, f"分支 C 选择分类兜底：完成 ({sec + 1}s)")
                return True
            time.sleep(0.8)

        ready = _branch_c_fallback_category_ready(page)
        if not ready:
            _log(account_id, label, "分支 C 选择分类兜底：未能确认类目就绪")
        return ready
    except Exception as exc:
        _log(account_id, label, f"分支 C 选择分类兜底：异常已吞掉（{exc}）")
        return False

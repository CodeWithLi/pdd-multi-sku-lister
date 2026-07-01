"""
分支 C + 已填标题：主页面出现「选择分类」→ 弹窗「最近使用」首条 →「确认」。

适用场景（与其它选类路径互斥）：
- 形态 B 简化页：商品主图 + 商品标题已填，商品分类区已渲染
- 暂无推荐分类，主页面有「选择分类」按钮（非已打开的三列选类器）
- 非「以图推荐分类」弹窗

不适用：
- 类目已选完整 / 可直通下一步
- 传统三列选类页（页面上已有搜索框，走 keyword/recent 模块）
- 无标题或非 page_ai 标题流（走原有 manual 搜索）
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

_READ_TITLED_MANUAL_STATE_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
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
    for (let i = 0; i < 12 && node; i++) {
        const t = (node.innerText || node.textContent || '').slice(0, 160);
        if (t.includes('最近使用')) return true;
        node = node.parentElement;
    }
    return false;
}
function findPickerModal() {
    const selectors = [
        '[data-testid="beast-core-modal"]',
        '[class*="beast-core-modal"]',
        '[role="dialog"]',
        '[class*="modal"]',
        '[class*="Modal"]',
        '[class*="dialog"]',
        '[class*="Dialog"]',
    ];
    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            if (!isVisible(el)) continue;
            const t = el.innerText || el.textContent || '';
            if (!t.includes('选择商品分类')) continue;
            if (!t.includes('最近使用') && !t.includes('请输入关键词搜索分类')) continue;
            return el;
        }
    }
    return null;
}
function hasSelectCategoryButton() {
    for (const el of document.querySelectorAll('button, a, span, div')) {
        const t = (el.innerText || el.textContent || '').trim();
        if (t !== '选择分类' || !isVisible(el)) continue;
        const modal = findPickerModal();
        if (modal && modal.contains(el)) continue;
        return true;
    }
    return false;
}
const body = document.body?.innerText || '';
const compact = norm(body);
const modal = findPickerModal();
const modalOpen = !!modal;
const searchOnMain = !!document.querySelector(
    'input[placeholder="请输入关键词搜索分类"]'
);
const recentPaths = [];
const recentRoot = modal || document.body;
for (const el of recentRoot.querySelectorAll('div, span, a, li, button')) {
    if (!isVisible(el) || !isInRecentSection(el)) continue;
    const t = cleanPath(el.innerText || el.textContent || '');
    if (!isCategoryPath(t) || t.includes('清空')) continue;
    if (!recentPaths.includes(t)) recentPaths.push(t);
}
return {
    modalOpen,
    selectButtonVisible: hasSelectCategoryButton(),
    searchOnMain,
    blocking: body.includes('请选择完整的分类') || body.includes('请选择完整分类'),
    noRecommendation: body.includes('暂无推荐的分类')
        || (body.includes('暂无推荐') && body.includes('手动选择')),
    hasPublishForm: body.includes('商品主图') && body.includes('商品标题'),
    recentPaths,
};
"""

_CLICK_SELECT_CATEGORY_BUTTON_JS = """
function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none' && s.visibility !== 'hidden';
}
for (const el of document.querySelectorAll('button, a, span, div')) {
    const t = (el.innerText || el.textContent || '').trim();
    if (t !== '选择分类' || !isVisible(el)) continue;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    el.click();
    return true;
}
return false;
"""

_CLICK_FIRST_RECENT_IN_PICKER_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
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
    for (let i = 0; i < 12 && node; i++) {
        const t = (node.innerText || node.textContent || '').slice(0, 160);
        if (t.includes('最近使用')) return true;
        node = node.parentElement;
    }
    return false;
}
function findPickerModal() {
    for (const el of document.querySelectorAll(
        '[data-testid="beast-core-modal"], [class*="modal"], [class*="Modal"], [role="dialog"], [class*="dialog"], [class*="Dialog"]'
    )) {
        if (!isVisible(el)) continue;
        const t = el.innerText || el.textContent || '';
        if (!t.includes('选择商品分类')) continue;
        return el;
    }
    return null;
}
function clickEl(el) {
    if (!el || !isVisible(el)) return false;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    el.click();
    return true;
}
const root = findPickerModal() || document.body;
const candidates = [];
for (const el of root.querySelectorAll('div, span, a, li, button')) {
    if (!isVisible(el) || !isInRecentSection(el)) continue;
    const t = cleanPath(el.innerText || el.textContent || '');
    if (!isCategoryPath(t) || t.includes('清空')) continue;
    const r = el.getBoundingClientRect();
    candidates.push({ el, t, top: r.top, left: r.left, area: r.width * r.height });
}
if (!candidates.length) return { ok: false, text: '', reason: 'no_recent' };
candidates.sort((a, b) => a.top - b.top || a.left - b.left || a.area - b.area);
const pick = candidates[0];
if (clickEl(pick.el)) {
    return { ok: true, text: pick.t.slice(0, 120), reason: 'recent_first' };
}
return { ok: false, text: pick.t.slice(0, 120), reason: 'click_failed' };
"""

_CLICK_PICKER_CONFIRM_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
function findPickerModal() {
    for (const el of document.querySelectorAll(
        '[data-testid="beast-core-modal"], [class*="modal"], [class*="Modal"], [role="dialog"], [class*="dialog"], [class*="Dialog"]'
    )) {
        if (!isVisible(el)) continue;
        const t = el.innerText || el.textContent || '';
        if (!t.includes('选择商品分类')) continue;
        return el;
    }
    return null;
}
const root = findPickerModal() || document.body;
const buttons = [];
for (const el of root.querySelectorAll('button, a, span, div')) {
    const t = norm(el.innerText || el.textContent || '');
    if (t !== '确认' || !isVisible(el)) continue;
    const full = norm(el.innerText || el.textContent || '');
    if (full.includes('确认发布')) continue;
    const r = el.getBoundingClientRect();
    buttons.push({ el, x: r.left + r.width / 2, y: r.top + r.height / 2, area: r.width * r.height });
}
if (!buttons.length) return { ok: false, reason: 'no_confirm' };
buttons.sort((a, b) => b.x - a.x || b.area - a.area);
try {
    buttons[0].el.scrollIntoView({ block: 'center', behavior: 'instant' });
    buttons[0].el.click();
    return { ok: true, reason: 'confirm' };
} catch (e) {
    return { ok: false, reason: 'confirm_click_failed' };
}
"""


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def read_branch_c_titled_manual_state(page: DpPage) -> dict[str, Any]:
    try:
        raw = page.run_js(_READ_TITLED_MANUAL_STATE_JS)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def branch_c_has_filled_title(page: DpPage, listing_info: dict[str, Any] | None) -> bool:
    from pdd_agent.skills.listing.page_ai_title import _read_title_from_input

    title = str(_read_title_from_input(page) or "").strip()
    if len(title) >= 2:
        return True
    return len(str((listing_info or {}).get("title") or "").strip()) >= 2


def branch_c_is_manual_category_picker_modal_open(page: DpPage) -> bool:
    state = read_branch_c_titled_manual_state(page)
    return bool(state.get("modalOpen"))


def branch_c_needs_titled_manual_category_pick(
    page: DpPage,
    listing_info: dict[str, Any] | None,
) -> bool:
    """
    带标题 + 主页面「选择分类」入口 或 选类弹窗已打开且尚未选完整类目。
    """
    from pdd_agent.skills.listing.category_branch_c_modal import (
        is_image_category_recommendation_modal_visible,
        is_modal_blocking_category_advance,
    )
    from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
        _listing_uses_page_ai_title_mode,
    )
    from pdd_agent.skills.listing.category_branch_c_recent import (
        branch_c_category_path_ready_strict,
    )

    if not _listing_uses_page_ai_title_mode(listing_info):
        return False
    if not branch_c_has_filled_title(page, listing_info):
        return False
    if branch_c_category_path_ready_strict(page):
        return False
    if is_image_category_recommendation_modal_visible(page):
        return False
    if is_modal_blocking_category_advance(page):
        return False

    state = read_branch_c_titled_manual_state(page)
    if not state.get("hasPublishForm"):
        return False

    if state.get("modalOpen"):
        return bool(state.get("recentPaths"))

    if state.get("searchOnMain"):
        return False

    if not state.get("selectButtonVisible"):
        return False

    return bool(
        state.get("noRecommendation")
        or state.get("blocking")
    )


def branch_c_click_select_category_button(page: DpPage) -> bool:
    from pdd_agent.skills.listing import upload as listing_upload

    if listing_upload._open_category_selector_panel(page):
        return True
    try:
        return bool(page.run_js(_CLICK_SELECT_CATEGORY_BUTTON_JS))
    except Exception:
        return False


def branch_c_click_first_recent_in_picker_modal(page: DpPage) -> tuple[bool, str]:
    try:
        raw = page.run_js(_CLICK_FIRST_RECENT_IN_PICKER_JS)
        info = raw if isinstance(raw, dict) else {}
    except Exception:
        info = {}
    if info.get("ok"):
        return True, str(info.get("text") or "")
    return False, str(info.get("text") or info.get("reason") or "")


def branch_c_confirm_manual_category_picker_modal(page: DpPage) -> bool:
    try:
        raw = page.run_js(_CLICK_PICKER_CONFIRM_JS)
        info = raw if isinstance(raw, dict) else {}
    except Exception:
        info = {}
    return bool(info.get("ok"))


def run_branch_c_titled_manual_category_pick(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any] | None = None,
    *,
    max_wait: int = 15,
) -> bool:
    """
    带标题分支 C：选择分类 → 最近使用首条 → 确认 → 等待类目就绪。
    """
    from pdd_agent.skills.listing import upload as listing_upload
    from pdd_agent.skills.listing.category_branch_c_recent import (
        branch_c_category_path_ready_strict,
    )

    if branch_c_category_path_ready_strict(page):
        _log(account_id, label, "分支 C 带标题选类：类目已就绪，跳过")
        return True

    state = read_branch_c_titled_manual_state(page)
    _log(
        account_id,
        label,
        "分支 C 带标题选类："
        f"select_btn={bool(state.get('selectButtonVisible'))} "
        f"modal={bool(state.get('modalOpen'))} "
        f"recent={len(state.get('recentPaths') or [])}",
    )

    if not state.get("modalOpen"):
        if not state.get("selectButtonVisible"):
            _log(account_id, label, "分支 C 带标题选类：未找到「选择分类」按钮")
            return False
        _log(account_id, label, "分支 C 带标题选类 Step1/3：点击「选择分类」")
        if not branch_c_click_select_category_button(page):
            _log(account_id, label, "分支 C 带标题选类：点击「选择分类」失败")
            return False
        time.sleep(1.2)

    for sec in range(max_wait):
        state = read_branch_c_titled_manual_state(page)
        if not state.get("modalOpen"):
            if branch_c_category_path_ready_strict(page):
                return True
            if sec >= 3 and state.get("selectButtonVisible"):
                branch_c_click_select_category_button(page)
            time.sleep(0.8)
            continue

        if not state.get("recentPaths"):
            time.sleep(0.8)
            continue

        _log(account_id, label, "分支 C 带标题选类 Step2/3：点击「最近使用」首条")
        clicked, picked_text = branch_c_click_first_recent_in_picker_modal(page)
        if not clicked:
            _log(account_id, label, f"分支 C 带标题选类：最近使用点击失败（{picked_text}）")
            time.sleep(0.8)
            continue
        _log(account_id, label, f"分支 C 带标题选类：已选「{picked_text}」")
        time.sleep(0.6)

        _log(account_id, label, "分支 C 带标题选类 Step3/3：点击弹窗「确认」")
        if not branch_c_confirm_manual_category_picker_modal(page):
            _log(account_id, label, "分支 C 带标题选类：点击「确认」失败，重试…")
            time.sleep(0.8)
            continue
        time.sleep(0.8)
        listing_upload._dismiss_category_search_overlay(page, account_id, label)

        if branch_c_category_path_ready_strict(page):
            _log(account_id, label, f"分支 C 带标题选类：完成 ({sec + 1}s)")
            return True

        listing_upload._confirm_category_picker_selection(page, account_id, label)
        time.sleep(0.8)

    ready = branch_c_category_path_ready_strict(page)
    if not ready:
        _log(account_id, label, "分支 C 带标题选类：超时，类目仍未就绪")
    return ready


def log_branch_c_titled_picker_diagnostics(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = read_branch_c_titled_manual_state(page)
    info = {
        "has_title": branch_c_has_filled_title(page, listing_info),
        "needs_titled_pick": branch_c_needs_titled_manual_category_pick(page, listing_info),
        "select_button": bool(state.get("selectButtonVisible")),
        "modal_open": bool(state.get("modalOpen")),
        "recent_count": len(state.get("recentPaths") or []),
        "blocking": bool(state.get("blocking")),
    }
    _log(
        account_id,
        label,
        "分支 C 带标题选类诊断："
        f"needs={info['needs_titled_pick']} title={info['has_title']} "
        f"select={info['select_button']} modal={info['modal_open']} "
        f"recent={info['recent_count']} blocking={info['blocking']}",
    )
    if state.get("recentPaths"):
        preview = " | ".join(str(p) for p in (state.get("recentPaths") or [])[:2])
        _log(account_id, label, f"分支 C 带标题选类最近使用：{preview[:200]}")
    return info

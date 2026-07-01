"""分支 C：检测类目是否已选 + 「最近使用」回退选类。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

_READ_SELECTION_STATE_JS = """
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
    for (let i = 0; i < 10 && node; i++) {
        const t = (node.innerText || node.textContent || '').slice(0, 120);
        if (t.includes('最近使用')) return true;
        node = node.parentElement;
    }
    return false;
}
const body = document.body?.innerText || '';
const compact = norm(body);
const blocking = body.includes('请选择完整的分类')
    || body.includes('请选择完整分类');
const onPage = !!document.querySelector('input[placeholder="请输入关键词搜索分类"]')
    || (body.includes('第2步') && body.includes('选择商品分类'))
    || (body.includes('最近使用') && body.includes('下一步'));
const autoSelected = compact.includes('已根据主轮播图选择分类');
let explicitSelected = compact.includes('已选分类') && body.includes('>');
if (!explicitSelected && !blocking) {
    for (const el of document.querySelectorAll('div, span, p, li')) {
        if (!isVisible(el) || isInRecentSection(el)) continue;
        const t = cleanPath(el.innerText || el.textContent || '');
        if (t.startsWith('已选分类') && isCategoryPath(t.replace(/^已选分类/, ''))) {
            explicitSelected = true;
            break;
        }
    }
}
const recentPaths = [];
for (const el of document.querySelectorAll('div, span, a, li, button')) {
    if (!isVisible(el) || !isInRecentSection(el)) continue;
    const t = cleanPath(el.innerText || el.textContent || '');
    if (!isCategoryPath(t)) continue;
    if (t.includes('清空')) continue;
    if (!recentPaths.includes(t)) recentPaths.push(t);
}
const pathReady = onPage && !blocking && (autoSelected || explicitSelected);
return {
    onPage,
    blocking,
    autoSelected,
    explicitSelected,
    pathReady,
    recentPaths,
};
"""

_CLICK_RECENT_PATH_JS = """
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
    for (let i = 0; i < 10 && node; i++) {
        const t = (node.innerText || node.textContent || '').slice(0, 120);
        if (t.includes('最近使用')) return true;
        node = node.parentElement;
    }
    return false;
}
function clickEl(el) {
    if (!el || !isVisible(el)) return false;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    el.click();
    return true;
}
const prefer = cleanPath(arguments[0] || '');
const candidates = [];
for (const el of document.querySelectorAll('div, span, a, li, button')) {
    if (!isVisible(el) || !isInRecentSection(el)) continue;
    const t = cleanPath(el.innerText || el.textContent || '');
    if (!isCategoryPath(t) || t.includes('清空')) continue;
    const r = el.getBoundingClientRect();
    candidates.push({ el, t, area: r.width * r.height });
}
if (!candidates.length) return { ok: false, text: '', reason: 'no_recent' };
candidates.sort((a, b) => a.area - b.area);
let pick = candidates[0];
if (prefer) {
    const hit = candidates.find((c) => c.t.includes(prefer));
    if (hit) pick = hit;
}
if (clickEl(pick.el)) {
    return { ok: true, text: pick.t.slice(0, 120), reason: 'recent' };
}
return { ok: false, text: pick.t.slice(0, 120), reason: 'click_failed' };
"""


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def read_branch_c_category_selection_state(page: DpPage) -> dict[str, Any]:
    try:
        raw = page.run_js(_READ_SELECTION_STATE_JS)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def branch_c_category_path_ready_strict(page: DpPage) -> bool:
    """严格判定：PDD 已选完整类目（非「最近使用」展示项）。"""
    state = read_branch_c_category_selection_state(page)
    return bool(state.get("pathReady"))


def branch_c_needs_recent_category_pick(page: DpPage) -> bool:
    """未选完整类目且存在「最近使用」路径时可回退点击。"""
    from pdd_agent.skills.listing.category_branch_c_modal import (
        is_modal_blocking_category_advance,
    )

    if is_modal_blocking_category_advance(page):
        return False
    state = read_branch_c_category_selection_state(page)
    if not state.get("onPage"):
        return False
    if state.get("pathReady"):
        return False
    if not state.get("recentPaths"):
        return False
    return bool(state.get("blocking")) or not (
        state.get("autoSelected") or state.get("explicitSelected")
    )


def run_branch_c_recent_category_pick(
    page: DpPage,
    account_id: str,
    label: str,
    category_keyword: str = "",
    *,
    max_wait: int = 12,
) -> bool:
    """点击「最近使用」首条（优先匹配 category_keyword）完成选类。"""
    from pdd_agent.skills.listing import upload as listing_upload

    keyword = str(category_keyword or "").strip()
    state = read_branch_c_category_selection_state(page)
    paths = list(state.get("recentPaths") or [])
    if not paths:
        _log(account_id, label, "分支 C 最近使用：页面上无可用类目路径")
        return False

    _log(
        account_id,
        label,
        f"分支 C 最近使用：准备点击回退类目（候选 {len(paths)} 条，优先关键词={keyword or '无'}）",
    )
    try:
        raw = page.run_js(_CLICK_RECENT_PATH_JS, keyword)
        info = raw if isinstance(raw, dict) else {}
    except Exception:
        info = {}

    if info.get("ok"):
        _log(account_id, label, f"分支 C 最近使用：已点击「{info.get('text', '')}」")
    else:
        _log(
            account_id,
            label,
            f"分支 C 最近使用：点击失败 reason={info.get('reason', 'unknown')}",
        )
        return False

    time.sleep(0.8)
    listing_upload._confirm_category_picker_selection(page, account_id, label)
    listing_upload._dismiss_category_search_overlay(page, account_id, label)

    for sec in range(max_wait):
        if branch_c_category_path_ready_strict(page):
            _log(account_id, label, f"分支 C 最近使用：类目已就绪 ({sec + 1}s)")
            return True
        listing_upload._confirm_category_picker_selection(page, account_id, label)
        time.sleep(1)

    ready = branch_c_category_path_ready_strict(page)
    if not ready:
        _log(account_id, label, "分支 C 最近使用：点击后仍未检测到完整类目")
    return ready


def log_branch_c_recent_diagnostics(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    state = read_branch_c_category_selection_state(page)
    info = {
        "on_page": bool(state.get("onPage")),
        "blocking": bool(state.get("blocking")),
        "auto_selected": bool(state.get("autoSelected")),
        "explicit_selected": bool(state.get("explicitSelected")),
        "path_ready": bool(state.get("pathReady")),
        "recent_count": len(state.get("recentPaths") or []),
        "needs_recent": branch_c_needs_recent_category_pick(page),
    }
    _log(
        account_id,
        label,
        "分支 C 选类状态："
        f"on_page={info['on_page']} blocking={info['blocking']} "
        f"auto={info['auto_selected']} explicit={info['explicit_selected']} "
        f"path_ready={info['path_ready']} recent={info['recent_count']} "
        f"needs_recent={info['needs_recent']}",
    )
    if state.get("recentPaths"):
        preview = " | ".join(str(p) for p in (state.get("recentPaths") or [])[:2])
        _log(account_id, label, f"分支 C 最近使用预览：{preview[:200]}")
    return info


def ensure_branch_c_category_selected(
    page: DpPage,
    account_id: str,
    label: str,
    category_keyword: str,
) -> bool:
    """
    确保分支 C 类目已选：已自动选中则跳过；否则点「最近使用」；再不行走关键词搜索。
    """
    from pdd_agent.skills.listing.category_branch_c_picker import (
        branch_c_needs_keyword_category_pick,
        run_branch_c_keyword_category_pick,
    )

    log_branch_c_recent_diagnostics(page, account_id, label)
    if branch_c_category_path_ready_strict(page):
        _log(account_id, label, "分支 C：类目已选（自动/已选分类），可直接点下一步")
        return True

    if branch_c_needs_recent_category_pick(page):
        _log(account_id, label, "分支 C：未检测到完整类目，尝试「最近使用」")
        if run_branch_c_recent_category_pick(
            page,
            account_id,
            label,
            category_keyword,
        ):
            return True

    if branch_c_needs_keyword_category_pick(page):
        _log(account_id, label, "分支 C：最近使用未成功，改走关键词搜索选类")
        return run_branch_c_keyword_category_pick(
            page,
            account_id,
            label,
            category_keyword,
        )

    return branch_c_category_path_ready_strict(page)

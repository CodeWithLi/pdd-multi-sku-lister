"""
营销活动页 — 「待报名商品」区块守卫。

与 marketing_activities.py 解耦：页顶「待报名商品」异步加载后会：
1. 把「营销活动报名」挤到视口下方
2. 误点「查询 / 确认报名 / 去报名」会弹出「搜索活动商品」「商品活动报名」等遮挡层

搜索活动 ID 前应滚动到「营销活动报名」、关闭误开弹窗、取消待报名区勾选。
"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)

# 搜索阶段误开的弹窗（与正式选品弹窗「搜索商品」不同）
_UNEXPECTED_PENDING_MODAL_TITLES: tuple[str, ...] = (
    "搜索活动商品",
    "商品活动报名",
)

_SCROLL_TO_REGISTRATION_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 8 && r.height > 8
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
function findExactTitle(text) {
    const target = norm(text);
    const hits = Array.from(document.querySelectorAll('div,span,h1,h2,h3,p,label,section'))
        .filter(isVisible)
        .filter((el) => norm(el.innerText || el.textContent || '') === target);
    hits.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    return hits[0] || null;
}
const title = findExactTitle('营销活动报名');
if (!title) {
    return { scrolled: false, reason: 'registration_title_not_found' };
}
title.scrollIntoView({ block: 'start', inline: 'nearest' });
window.scrollBy(0, -80);
return { scrolled: true, method: 'marketing_registration_title', top: title.getBoundingClientRect().top };
"""

_DISMISS_UNEXPECTED_MODALS_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 40 && r.height > 40
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
const unexpectedTitles = (arguments[0] || []).map(norm);

function modalTitle(modal) {
    const text = norm(modal.innerText || modal.textContent || '').slice(0, 500);
    for (const title of unexpectedTitles) {
        if (text.startsWith(title) || text.includes(title)) return title;
    }
    return '';
}
function findUnexpectedModals() {
    const selectors = [
        '[data-testid="beast-core-modal"]',
        '[data-testid="beast-core-modal-container"]',
        '[class*="MDL_modal"]',
        '[role="dialog"]',
    ];
    const seen = new Set();
    const out = [];
    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            if (!isVisible(el) || seen.has(el)) continue;
            seen.add(el);
            const title = modalTitle(el);
            if (!title) continue;
            out.push({ el, title });
        }
    }
    return out;
}
function clickTarget(el) {
    if (!el) return false;
    let cur = el;
    for (let i = 0; i < 6 && cur && cur !== document.body; i++) {
        if (typeof cur.click === 'function') {
            cur.click();
            return true;
        }
        cur = cur.parentElement;
    }
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    return true;
}
function clickClose(modal) {
    const scope = modal;
    const closeIcon = scope.querySelector('[data-testid="beast-core-modal-icon-close"]')
        || scope.querySelector('[data-testid="beast-core-icon-close"]')
        || Array.from(scope.querySelectorAll('[class*="CloseIcon"],[class*="closeIcon"]')).find(isVisible);
    if (closeIcon && clickTarget(closeIcon)) {
        return { clicked: true, method: 'close_icon' };
    }
    const buttons = Array.from(scope.querySelectorAll('button, a, span, div'))
        .filter(isVisible)
        .map((el) => ({ el, text: norm(el.innerText || el.textContent || '') }));
    const cancelBtn = buttons.find((item) => item.text === '取消' || item.text === '关闭');
    if (cancelBtn && clickTarget(cancelBtn.el)) {
        return { clicked: true, method: 'cancel_button' };
    }
    return { clicked: false, method: 'not_found' };
}

const modals = findUnexpectedModals();
if (!modals.length) {
    return { dismissed: false, present: false, reason: 'no_unexpected_modal' };
}
const target = modals[0];
const click = clickClose(target.el);
return {
    dismissed: !!click.clicked,
    present: true,
    title: target.title,
    click,
};
"""

_UNCHECK_PENDING_PRODUCTS_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
function inPendingSection(el) {
    let cur = el;
    for (let i = 0; i < 25 && cur; i++) {
        const text = norm(cur.innerText || cur.textContent || '').slice(0, 3000);
        if (text.includes('待报名商品') && !text.includes('营销活动报名')) return true;
        cur = cur.parentElement;
    }
    return false;
}
let unchecked = 0;
for (const input of document.querySelectorAll('input[type="checkbox"]')) {
    if (!isVisible(input) || !input.checked || !inPendingSection(input)) continue;
    input.click();
    unchecked += 1;
}
return { unchecked, acted: unchecked > 0 };
"""


def _log(account_id: str, message: str, **extra: Any) -> None:
    prefix = f"[{account_id}] [待报名商品守卫]" if account_id else "[待报名商品守卫]"
    parts = [f"{key}={value}" for key, value in extra.items() if value is not None and value != ""]
    line = f"{prefix} {message}"
    if parts:
        line = f"{line} | {' '.join(parts)}"
    logger.info(line)
    print(line, flush=True)


def _brief(value: Any, *, limit: int = 200) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}..."


def scroll_to_marketing_registration_section(page: DpPage, account_id: str = "") -> dict[str, Any]:
    """滚动到「营销活动报名」标题，避免在页顶「待报名商品」区域操作。"""
    try:
        raw = page.run_js(_SCROLL_TO_REGISTRATION_JS)
        result = raw if isinstance(raw, dict) else {"scrolled": False}
        if result.get("scrolled") and account_id:
            _log(account_id, "已滚动到营销活动报名区", method=result.get("method"))
        time.sleep(0.4)
        return result
    except Exception as exc:
        return {"scrolled": False, "error": str(exc)}


def dismiss_unexpected_pending_modals(page: DpPage, account_id: str = "") -> dict[str, Any]:
    """关闭误开的「搜索活动商品 / 商品活动报名」弹窗。"""
    try:
        raw = page.run_js(_DISMISS_UNEXPECTED_MODALS_JS, list(_UNEXPECTED_PENDING_MODAL_TITLES))
        result = raw if isinstance(raw, dict) else {}
        if result.get("dismissed") and account_id:
            _log(account_id, "已关闭误开弹窗", title=result.get("title"), method=result.get("click", {}).get("method"))
        if result.get("dismissed"):
            time.sleep(0.5)
        return result
    except Exception as exc:
        return {"dismissed": False, "error": str(exc)}


def uncheck_pending_product_selection(page: DpPage, account_id: str = "") -> dict[str, Any]:
    """取消「待报名商品」区已勾选商品，避免误触「确认报名」。"""
    try:
        raw = page.run_js(_UNCHECK_PENDING_PRODUCTS_JS)
        result = raw if isinstance(raw, dict) else {}
        if result.get("acted") and account_id:
            _log(account_id, "已取消待报名商品勾选", count=result.get("unchecked"))
        return result
    except Exception as exc:
        return {"acted": False, "error": str(exc)}


def prepare_marketing_registration_surface(
    page: DpPage,
    account_id: str = "",
    *,
    max_modal_attempts: int = 3,
) -> dict[str, Any]:
    """
    搜索活动 ID 前的页面准备：
    关误开弹窗 → 取消待报名勾选 → 滚到营销活动报名区。
    """
    if account_id:
        _log(account_id, "开始准备营销活动报名区", url=getattr(page, "url", ""))

    modals: list[dict[str, Any]] = []
    for attempt in range(max(1, max_modal_attempts)):
        one = dismiss_unexpected_pending_modals(page, account_id)
        modals.append(one)
        if account_id and one.get("present"):
            _log(
                account_id,
                f"检查误开弹窗: {'发现' if one.get('present') else '无'}",
                attempt=attempt + 1,
                title=one.get("title"),
                dismissed=one.get("dismissed"),
                method=one.get("click", {}).get("method"),
            )
        if not one.get("dismissed"):
            break

    unchecked = uncheck_pending_product_selection(page, account_id)
    if account_id:
        _log(
            account_id,
            f"取消待报名勾选: {'已处理' if unchecked.get('acted') else '无需处理'}",
            count=unchecked.get("unchecked"),
        )

    scroll = scroll_to_marketing_registration_section(page, account_id)
    if account_id and not scroll.get("scrolled"):
        _log(account_id, "滚动失败", reason=scroll.get("reason") or scroll.get("error") or "unknown")

    result = {
        "modals": modals,
        "unchecked": unchecked,
        "scroll": scroll,
        "ready": bool(scroll.get("scrolled")),
    }
    if account_id:
        _log(account_id, "准备完成", ready=result.get("ready"), detail=_brief(result))
    return result


__all__ = [
    "dismiss_unexpected_pending_modals",
    "prepare_marketing_registration_surface",
    "scroll_to_marketing_registration_section",
    "uncheck_pending_product_selection",
]

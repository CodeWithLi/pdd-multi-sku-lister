"""
营销活动报名区 — 活动 ID 搜索框定位。

与 marketing_activities.py 解耦：页顶「待报名商品」也有 ID 搜索框（placeholder 含「商品ID搜索」），
原逻辑用宽泛的「ID搜索」会误匹配并在错误输入框填入活动 ID。
本模块仅定位「营销活动报名」区块内的活动名称/ID 搜索框。
"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)

MIN_REGISTRATION_SECTION_SCORE = 40

# 「待报名商品」区商品 ID 搜索框特征
_PENDING_PRODUCT_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "商品ID搜索",
    "输入商品ID",
    "搜索商品",
)

# 「营销活动报名」区活动搜索框特征
_ACTIVITY_SEARCH_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "活动名称或ID",
    "活动名称",
)

_SCOPED_INPUT_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 40 && r.height > 10
        && s.display !== 'none'
        && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }

const pendingMarkers = arguments[0] || [];
const activityMarkers = arguments[1] || [];

function isPendingProductSearchPlaceholder(ph) {
    const c = norm(ph);
    if (!c) return false;
    if (pendingMarkers.some((m) => c.includes(norm(m)))) return true;
    if (c.includes('商品') && c.includes('ID') && !c.includes('活动名称')) return true;
    return false;
}
function isActivityRegistrationSearchPlaceholder(ph) {
    const c = norm(ph);
    if (!c || isPendingProductSearchPlaceholder(ph)) return false;
    if (c.includes('活动名称或ID')) return true;
    return c.includes('活动名称') && c.includes('ID');
}
function sectionScoreForInput(input) {
    let score = 0;
    let el = input;
    for (let i = 0; i < 30 && el; i++) {
        const text = norm(el.innerText || el.textContent || '').slice(0, 4000);
        if (text.includes('营销活动报名')) score += 80;
        if (text.includes('全部活动') || text.includes('我能参加的活动') || text.includes('我收藏的活动')) {
            score += 40;
        }
        if (text.includes('活动大厅')) score += 15;
        if (text.includes('待报名商品') && !text.includes('营销活动报名')) score -= 60;
        el = el.parentElement;
    }
    return score;
}
function isTopElementAt(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const x = Math.min(Math.max(r.left + r.width / 2, 1), window.innerWidth - 2);
    const y = Math.min(Math.max(r.top + r.height / 2, 1), window.innerHeight - 2);
    const top = document.elementFromPoint(x, y);
    if (!top) return false;
    return el === top || el.contains(top) || top.contains(el);
}
function collectScopedInputs() {
    return Array.from(document.querySelectorAll(
        'input[data-testid="beast-core-input-nativeInput"], input[data-testid="beast-core-input-htmlInput"], input'
    ))
        .filter(isVisible)
        .map((el) => ({
            el,
            placeholder: (el.getAttribute('placeholder') || '').trim(),
            rect: el.getBoundingClientRect(),
            score: sectionScoreForInput(el),
            clickable: isTopElementAt(el),
            testid: el.getAttribute('data-testid') || '',
        }))
        .filter((item) => isActivityRegistrationSearchPlaceholder(item.placeholder));
}
function pickBestInput(items) {
    if (!items.length) return null;
    items.sort((a, b) => {
        if (b.score !== a.score) return b.score - a.score;
        if (b.clickable !== a.clickable) return (b.clickable ? 1 : 0) - (a.clickable ? 1 : 0);
        return b.rect.top - a.rect.top;
    });
    const best = items[0];
    if ((best.score || 0) < 40) return null;
    return best;
}

const mode = arguments[2] || 'find';
const activityId = arguments[3] || '';

const candidates = collectScopedInputs();
const best = pickBestInput(candidates);
if (!best) {
    return {
        found: false,
        filled: false,
        reason: 'activity_registration_search_input_not_found',
        rejected_pending_product: true,
    };
}

const input = best.el;
input.scrollIntoView({ block: 'center', inline: 'nearest' });

if (mode === 'find') {
    input.focus();
    return {
        found: true,
        placeholder: best.placeholder,
        value: input.value || '',
        section_score: best.score,
        clickable: best.clickable,
        testid: best.testid,
        top: Math.round(best.rect.top),
        scoped: true,
        method: 'scoped_js_find',
    };
}

function setInputValue(el, value) {
    el.focus();
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    if (setter) {
        setter.call(el, '');
    } else {
        el.value = '';
    }
    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward', data: null }));
    if (setter) {
        setter.call(el, value);
    } else {
        el.value = value;
    }
    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.blur();
}

setInputValue(input, activityId);
return {
    found: true,
    filled: (input.value || '') === activityId,
    value: input.value || '',
    placeholder: best.placeholder,
    method: 'scoped_react_input_setter',
    section_score: best.score,
    clickable: best.clickable,
    testid: best.testid,
    scoped: true,
};
"""

_CLICK_SCOPED_QUERY_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 20 && r.height > 16
        && s.display !== 'none'
        && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }

const pendingMarkers = arguments[0] || [];

function isPendingProductSearchPlaceholder(ph) {
    const c = norm(ph);
    if (!c) return false;
    if (pendingMarkers.some((m) => c.includes(norm(m)))) return true;
    if (c.includes('商品') && c.includes('ID') && !c.includes('活动名称')) return true;
    return false;
}
function isActivityRegistrationSearchPlaceholder(ph) {
    const c = norm(ph);
    if (!c || isPendingProductSearchPlaceholder(ph)) return false;
    if (c.includes('活动名称或ID')) return true;
    return c.includes('活动名称') && c.includes('ID');
}
function sectionScoreForInput(input) {
    let score = 0;
    let el = input;
    for (let i = 0; i < 30 && el; i++) {
        const text = norm(el.innerText || el.textContent || '').slice(0, 4000);
        if (text.includes('营销活动报名')) score += 80;
        if (text.includes('全部活动') || text.includes('我能参加的活动') || text.includes('我收藏的活动')) {
            score += 40;
        }
        if (text.includes('活动大厅')) score += 15;
        if (text.includes('待报名商品') && !text.includes('营销活动报名')) score -= 60;
        el = el.parentElement;
    }
    return score;
}
function isTopElementAt(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const x = Math.min(Math.max(r.left + r.width / 2, 1), window.innerWidth - 2);
    const y = Math.min(Math.max(r.top + r.height / 2, 1), window.innerHeight - 2);
    const top = document.elementFromPoint(x, y);
    if (!top) return false;
    return el === top || el.contains(top) || top.contains(el);
}
function collectScopedInputs() {
    return Array.from(document.querySelectorAll(
        'input[data-testid="beast-core-input-nativeInput"], input[data-testid="beast-core-input-htmlInput"], input'
    ))
        .filter(isVisible)
        .map((el) => ({
            el,
            placeholder: (el.getAttribute('placeholder') || '').trim(),
            rect: el.getBoundingClientRect(),
            score: sectionScoreForInput(el),
            clickable: isTopElementAt(el),
        }))
        .filter((item) => isActivityRegistrationSearchPlaceholder(item.placeholder));
}
function pickBestInput(items) {
    if (!items.length) return null;
    items.sort((a, b) => {
        if (b.score !== a.score) return b.score - a.score;
        if (b.clickable !== a.clickable) return (b.clickable ? 1 : 0) - (a.clickable ? 1 : 0);
        return b.rect.top - a.rect.top;
    });
    const best = items[0];
    if ((best.score || 0) < 40) return null;
    return best;
}

const candidates = collectScopedInputs();
const best = pickBestInput(candidates);
if (!best) {
    return { clicked: false, reason: 'scoped_search_input_not_found' };
}

const inputRect = best.el.getBoundingClientRect();
const buttons = Array.from(document.querySelectorAll('button, span, div, a'))
    .filter(isVisible)
    .map((el) => ({
        el,
        text: norm(el.innerText || el.textContent || ''),
        rect: el.getBoundingClientRect(),
    }))
    .filter((item) => item.text === '查询' || item.text === '搜索');

if (!buttons.length) {
    return { clicked: false, reason: 'scoped_search_button_not_found' };
}

const nearby = buttons
    .filter((item) => Math.abs(item.rect.top - inputRect.top) < 80)
    .sort((a, b) => Math.abs(a.rect.left - inputRect.right) - Math.abs(b.rect.left - inputRect.right));

if (!nearby.length) {
    return { clicked: false, reason: 'scoped_search_button_not_near_input' };
}

const target = nearby[0].el;
target.scrollIntoView({ block: 'center', inline: 'nearest' });
try {
    target.click();
} catch (e) {
    target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
}
return { clicked: true, text: '查询', method: 'scoped_near_input', scoped: true, section_score: best.score, clickable: best.clickable };
"""


def is_pending_product_search_placeholder(placeholder: str) -> bool:
    ph = (placeholder or "").strip()
    if not ph:
        return False
    if any(marker in ph for marker in _PENDING_PRODUCT_PLACEHOLDER_MARKERS):
        return True
    return "商品" in ph and "ID" in ph and "活动名称" not in ph


def is_activity_registration_search_placeholder(placeholder: str) -> bool:
    ph = (placeholder or "").strip()
    if not ph or is_pending_product_search_placeholder(ph):
        return False
    if "活动名称或ID" in ph:
        return True
    return "活动名称" in ph and "ID" in ph


def _run_scoped_js(
    page: DpPage,
    *,
    mode: str = "find",
    activity_id: str = "",
) -> dict[str, Any]:
    try:
        raw = page.run_js(
            _SCOPED_INPUT_JS,
            list(_PENDING_PRODUCT_PLACEHOLDER_MARKERS),
            list(_ACTIVITY_SEARCH_PLACEHOLDER_MARKERS),
            mode,
            str(activity_id or "").strip(),
        )
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        return {"found": False, "filled": False, "error": str(exc)}


def _read_scoped_input_value(page: DpPage) -> dict[str, Any]:
    return _run_scoped_js(page, mode="find")


def find_activity_search_input_scoped(page: DpPage, account_id: str = "") -> dict[str, Any]:
    """定位「营销活动报名」区块内的活动 ID 搜索框，排除「待报名商品」商品 ID 框。"""
    result = _run_scoped_js(page, mode="find")
    if account_id:
        logger.info(
            "[%s] [活动搜索框] js 定位 found=%s score=%s clickable=%s top=%s testid=%s value=%s reason=%s",
            account_id,
            result.get("found"),
            result.get("section_score"),
            result.get("clickable"),
            result.get("top"),
            result.get("testid"),
            result.get("value"),
            result.get("reason"),
        )
    return result


def fill_activity_search_input_scoped(page: DpPage, activity_id: str) -> dict[str, Any]:
    """向「营销活动报名」区块的活动搜索框填入活动 ID。"""
    safe_id = str(activity_id or "").strip()
    if not safe_id:
        return {"filled": False, "reason": "empty_activity_id", "scoped": True}

    before = _read_scoped_input_value(page)
    logger.info(
        "[活动搜索框] 填入前 found=%s score=%s clickable=%s value=%s",
        before.get("found"),
        before.get("section_score"),
        before.get("clickable"),
        before.get("value"),
    )

    js_result = _run_scoped_js(page, mode="fill", activity_id=safe_id)
    time.sleep(0.35)
    after = _read_scoped_input_value(page)
    actual = str(after.get("value") or js_result.get("value") or "").strip()

    if js_result.get("filled") and actual == safe_id:
        js_result["value"] = actual
        js_result["verified_by"] = "scoped_js_readback"
        logger.info(
            "[活动搜索框] js 填入成功 value=%s score=%s clickable=%s",
            actual,
            js_result.get("section_score"),
            js_result.get("clickable"),
        )
        return js_result

    raw_page = getattr(page, "_page", None)
    playwright_error = ""
    if raw_page is not None and after.get("found"):
        try:
            loc = raw_page.locator(
                'input[data-testid="beast-core-input-htmlInput"][placeholder*="活动名称或ID"], '
                'input[data-testid="beast-core-input-nativeInput"][placeholder*="活动名称或ID"]'
            ).last
            loc.scroll_into_view_if_needed(timeout=3_000)
            loc.fill(safe_id, timeout=5_000, force=True)
            time.sleep(0.3)
            actual = str(loc.input_value(timeout=2_000) or "").strip()
            if actual == safe_id:
                logger.info("[活动搜索框] playwright force 填入成功 value=%s", actual)
                return {
                    "filled": True,
                    "value": actual,
                    "method": "playwright_force_fill_last",
                    "scoped": True,
                }
        except Exception as exc:
            playwright_error = str(exc)

    fail = {
        "filled": False,
        "reason": "scoped_search_input_value_not_visible",
        "expected": safe_id,
        "actual": actual,
        "playwright_error": playwright_error,
        "js_result": js_result,
        "before": before,
        "after": after,
        "scoped": True,
    }
    logger.info(
        "[活动搜索框] 填入失败 expected=%s actual=%s pw_err=%s js_filled=%s js_reason=%s",
        safe_id,
        actual,
        playwright_error[:200] if playwright_error else "",
        js_result.get("filled"),
        js_result.get("reason"),
    )
    return fail


def click_activity_search_button_scoped(page: DpPage) -> dict[str, Any]:
    """点击「营销活动报名」搜索框旁的查询按钮。"""
    try:
        raw = page.run_js(
            _CLICK_SCOPED_QUERY_JS,
            list(_PENDING_PRODUCT_PLACEHOLDER_MARKERS),
        )
        result = raw if isinstance(raw, dict) else {"clicked": False, "reason": "scoped_click_js_failed"}
        logger.info(
            "[活动搜索框] 点击查询结果 clicked=%s method=%s reason=%s score=%s clickable=%s",
            result.get("clicked"),
            result.get("method"),
            result.get("reason"),
            result.get("section_score"),
            result.get("clickable"),
        )
        if result.get("clicked"):
            return result
    except Exception as exc:
        logger.info("[活动搜索框] js 点击查询异常: %s", exc)

    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        try:
            btn = raw_page.locator(
                'button[data-testid="beast-core-button"]:has-text("查询")'
            ).last
            btn.click(timeout=3_000, force=True)
            logger.info("[活动搜索框] playwright force 点击查询成功")
            return {"clicked": True, "text": "查询", "method": "playwright_force_query_last", "scoped": True}
        except Exception as exc:
            logger.info("[活动搜索框] playwright force 点击查询失败: %s", exc)
            return {"clicked": False, "reason": str(exc), "scoped": True}

    return {"clicked": False, "reason": "scoped_click_all_failed", "scoped": True}


__all__ = [
    "click_activity_search_button_scoped",
    "fill_activity_search_input_scoped",
    "find_activity_search_input_scoped",
    "is_activity_registration_search_placeholder",
    "is_pending_product_search_placeholder",
]

"""
营销活动页 — 关闭遮挡页面的运营/待办类弹窗。

与 marketing_activities.py 解耦：处理「不符合活动要求」等 beast-core-modal，
避免挡住活动名称/ID 搜索框。支持多种弹窗变体，优先点右上角 X，其次「稍后处理」。
"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)

# 业务必需弹窗：命中则绝不自动关
_BUSINESS_PROTECTED_MARKERS: tuple[str, ...] = (
    "搜索商品",
    "选择商品",
    "确认选择",
    "选择活动商品",
    "潜力商品报名",
    "确认提交",
    "取消流量保护",
    "流量保护",
    "活动价格",
    "批量设置",
    "规格预览",
    "充值推广",
    "创建推广",
)

# 已知可安全关闭的弹窗文案（数字可变，用部分匹配）
_SAFE_DISMISS_MARKERS: tuple[str, ...] = (
    "不符合活动要求",
    "影响活动权益",
    "请尽快修改",
    "活动权益",
    "待处理",
    "去设置",
    "立即参与",
    "立即配置",
    "经营地址",
    "登记实际经营",
    "确认补充",
    "去补充",
    "发布成功",
    "商品发布成功",
    "售罄提醒",
    "新消息",
    "查看全部",
    "合规",
    "外部平台",
    "营销电话",
    "设置营销电话",
)

_DISMISS_MARKETING_BLOCKING_MODAL_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
function zIndex(el) {
    let z = 0;
    let cur = el;
    for (let i = 0; i < 12 && cur; i++) {
        const zi = parseInt(window.getComputedStyle(cur).zIndex || '0', 10);
        if (!Number.isNaN(zi)) z = Math.max(z, zi);
        cur = cur.parentElement;
    }
    return z;
}
function clickable(el) {
    let cur = el;
    for (let i = 0; i < 6 && cur && cur !== document.body; i++) {
        const tag = (cur.tagName || '').toLowerCase();
        const role = cur.getAttribute?.('role') || '';
        const cls = (cur.className || '').toString().toLowerCase();
        if (tag === 'button' || tag === 'a' || role === 'button'
            || cls.includes('close')
            || cur.getAttribute?.('data-testid') === 'beast-core-icon-close'
            || cur.getAttribute?.('data-testid') === 'beast-core-modal-icon-close') {
            return cur;
        }
        cur = cur.parentElement;
    }
    return el;
}

const businessMarkers = arguments[0] || [];
const safeMarkers = arguments[1] || [];
const detectOnly = !!arguments[2];

function isBusinessProtected(text) {
    const c = norm(text);
    if (!c) return false;
    return businessMarkers.some((m) => c.includes(norm(m)));
}
function isSafeDismiss(text) {
    const c = norm(text);
    if (!c) return false;
    if (/\\d+个商品因不符合活动要求/.test(c)) return true;
    if (c.includes('不符合活动要求') && c.includes('活动权益')) return true;
    return safeMarkers.some((m) => c.includes(norm(m)));
}
function findModalRoots() {
    const selectors = [
        '[data-testid="beast-core-modal"]',
        '[data-testid="beast-core-modal-container"]',
        '[class*="MDL_modal"]',
        '[class*="MDL_wrapper"]',
        '[role="dialog"]',
    ];
    const seen = new Set();
    const roots = [];
    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            if (!isVisible(el) || seen.has(el)) continue;
            seen.add(el);
            const r = el.getBoundingClientRect();
            if (r.width < 80 || r.height < 60) continue;
            roots.push({ el, z: zIndex(el), area: r.width * r.height });
        }
    }
    roots.sort((a, b) => b.z - a.z || b.area - a.area);
    return roots.map((x) => x.el);
}
function findCloseIcon(scope) {
    const selectors = [
        '[data-testid="beast-core-modal-icon-close"]',
        '[data-testid="beast-core-icon-close"]',
        '[class*="headerCloseIcon"]',
        '[class*="CloseIcon"]',
        '[class*="closeIcon"]',
        '[aria-label="Close"]',
        '[aria-label="关闭"]',
    ];
    for (const sel of selectors) {
        const hit = Array.from(scope.querySelectorAll(sel)).find(isVisible);
        if (hit) return hit;
    }
    return null;
}
function findLaterButton(scope) {
    const buttons = Array.from(scope.querySelectorAll('button, a, span, div'));
    for (const el of buttons) {
        if (!isVisible(el)) continue;
        const text = norm(el.innerText || el.textContent || '');
        if (text === '稍后处理' || text === '知道了' || text === '我知道了' || text === '下次再说') {
            return el;
        }
    }
    return null;
}
function clickCloseOnModal(modalRoot) {
    if (!modalRoot) return { clicked: false, method: 'no_root' };
    const scope = modalRoot;
    const closeIcon = findCloseIcon(scope);
    if (closeIcon) {
        clickable(closeIcon).click();
        return { clicked: true, method: 'modal_close_icon' };
    }
    const laterBtn = findLaterButton(scope);
    if (laterBtn) {
        clickable(laterBtn).click();
        return { clicked: true, method: 'later_button' };
    }
    const modalRect = modalRoot.getBoundingClientRect?.()
        || { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    const candidates = [];
    for (const el of scope.querySelectorAll('button, a, span, i, svg, div')) {
        if (!isVisible(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.width > 72 || r.height > 72) continue;
        const text = (el.innerText || el.textContent || '').trim();
        const aria = (el.getAttribute?.('aria-label') || '').toLowerCase();
        const cls = (el.className || '').toString().toLowerCase();
        const nearTopRight = r.right >= modalRect.right - 120 && r.top <= modalRect.top + 100;
        if (!nearTopRight) continue;
        if (
            text === '×' || text === '✕' || text === 'X'
            || aria.includes('close') || aria.includes('关闭')
            || cls.includes('close')
        ) {
            candidates.push({ el, score: -(r.right) + r.top });
        }
    }
    candidates.sort((a, b) => a.score - b.score);
    if (candidates.length) {
        clickable(candidates[0].el).click();
        return { clicked: true, method: 'corner_candidate' };
    }
    return { clicked: false, method: 'not_found' };
}

const roots = findModalRoots();
if (!roots.length) {
    return { present: false, acted: false, reason: 'no_modal' };
}

for (const root of roots) {
    const text = root.innerText || root.textContent || '';
    if (isBusinessProtected(text)) {
        return {
            present: true,
            acted: false,
            skipped: true,
            reason: 'business_protected',
            preview: norm(text).slice(0, 60),
        };
    }
}

for (const root of roots) {
    const text = root.innerText || root.textContent || '';
    const hasClose = !!findCloseIcon(root);
    const hasLater = !!findLaterButton(root);
    const safe = isSafeDismiss(text);
    if (!safe && !(hasClose && !isBusinessProtected(text))) continue;

    if (detectOnly) {
        return {
            present: true,
            dismissible: true,
            preview: norm(text).slice(0, 80),
            has_close_icon: hasClose,
            has_later_button: hasLater,
            safe_marker: safe,
        };
    }

    const out = clickCloseOnModal(root);
    out.acted = !!out.clicked;
    out.present = true;
    out.preview = norm(text).slice(0, 80);
    out.safe_marker = safe;
    return out;
}

return { present: true, acted: false, reason: 'no_dismissible_modal' };
"""


def _log(account_id: str, message: str, **extra: Any) -> None:
    prefix = f"[{account_id}] [营销活动弹窗守卫]" if account_id else "[营销活动弹窗守卫]"
    parts = [f"{key}={value}" for key, value in extra.items() if value is not None and value != ""]
    line = f"{prefix} {message}"
    if parts:
        line = f"{line} | {' '.join(parts)}"
    logger.info(line)
    print(line, flush=True)


def _run_modal_js(page: DpPage, *, detect_only: bool = False) -> dict[str, Any]:
    try:
        raw = page.run_js(
            _DISMISS_MARKETING_BLOCKING_MODAL_JS,
            list(_BUSINESS_PROTECTED_MARKERS),
            list(_SAFE_DISMISS_MARKERS),
            detect_only,
        )
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        return {"acted": False, "error": str(exc)}


def detect_marketing_blocking_modal(page: DpPage) -> dict[str, Any]:
    """检测是否存在可安全关闭的营销活动遮挡弹窗。"""
    return _run_modal_js(page, detect_only=True)


def dismiss_one_marketing_blocking_modal(
    page: DpPage,
    account_id: str = "",
) -> dict[str, Any]:
    """尝试关闭一层营销活动遮挡弹窗。"""
    result = _run_modal_js(page, detect_only=False)
    if result.get("skipped"):
        return result
    if result.get("acted"):
        _log(
            account_id,
            "已关闭遮挡弹窗",
            method=result.get("method"),
            preview=(result.get("preview") or "")[:40],
        )
        time.sleep(0.5)
    return result


def ensure_marketing_blocking_modals_cleared(
    page: DpPage,
    account_id: str = "",
    *,
    max_attempts: int = 5,
) -> dict[str, Any]:
    """
    循环清理营销活动页上可安全关闭的遮挡弹窗。
    返回 dismissed 次数及最后一次检测结果。
    """
    dismissed = 0
    last: dict[str, Any] = {"acted": False}

    for _ in range(max(1, max_attempts)):
        last = dismiss_one_marketing_blocking_modal(page, account_id)
        if last.get("skipped"):
            break
        if not last.get("acted"):
            break
        dismissed += 1
        time.sleep(0.35)

    if dismissed:
        _log(account_id, f"共关闭 {dismissed} 层遮挡弹窗")

    return {
        "cleared": dismissed,
        "dismissed": dismissed > 0,
        "last": last,
    }


__all__ = [
    "detect_marketing_blocking_modal",
    "dismiss_one_marketing_blocking_modal",
    "ensure_marketing_blocking_modals_cleared",
]

"""拼多多发布流程中需点右上角 X 关闭的遮罩弹窗（与 upload 主流程隔离）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

_CLICK_MODAL_CLOSE_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
function clickable(el) {
    let cur = el;
    for (let i = 0; i < 6 && cur && cur !== document.body; i++) {
        const tag = (cur.tagName || '').toLowerCase();
        const role = cur.getAttribute?.('role') || '';
        const cls = (cur.className || '').toString().toLowerCase();
        if (tag === 'button' || tag === 'a' || role === 'button'
            || cls.includes('close') || cur.getAttribute?.('data-testid') === 'beast-core-icon-close') {
            return cur;
        }
        cur = cur.parentElement;
    }
    return el;
}
function findModal(kind) {
    const body = document.body?.innerText || '';
    const compact = norm(body);
    const roots = Array.from(document.querySelectorAll(
        '[data-testid="beast-core-modal"], [class*="beast-core-modal"], [role="dialog"], [class*="modal"], [class*="Modal"]'
    )).filter(isVisible);
    for (const el of roots) {
        const t = el.innerText || el.textContent || '';
        const c = norm(t);
        if (kind === 'image_space') {
            if (c.includes('图片空间') && (c.includes('确认') || c.includes('取消') || c.includes('全部文件'))) {
                return el;
            }
        }
        if (kind === 'post_publish') {
            if (c.includes('待处理') && (c.includes('去设置') || c.includes('立即参与') || c.includes('售罄'))) {
                return el;
            }
            if (c.includes('发布成功') || c.includes('商品发布成功')) {
                return el;
            }
        }
    }
    if (kind === 'image_space' && compact.includes('图片空间') && compact.includes('确认')) {
        return document.body;
    }
    if (kind === 'post_publish' && compact.includes('待处理') && compact.includes('去设置')) {
        return document.body;
    }
    return null;
}
function clickCloseOnModal(modalRoot) {
    if (!modalRoot) return { clicked: false, method: 'no_root' };
    const scope = modalRoot === document.body ? document : modalRoot;
    const exact = scope.querySelector?.('[data-testid="beast-core-icon-close"]')
        || Array.from(scope.querySelectorAll(
            '[data-testid="beast-core-icon-close"], [class*="closeIcon"], [class*="CloseIcon"], [class*="modal-close"], [aria-label="Close"], [aria-label="关闭"]'
        )).find(isVisible);
    if (exact) {
        clickable(exact).click();
        return { clicked: true, method: 'close_icon' };
    }
    const modalRect = modalRoot.getBoundingClientRect?.() || { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    const topRight = modalRect.right > 100 ? modalRect : { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    const candidates = [];
    for (const el of scope.querySelectorAll('button, a, span, i, svg, div')) {
        if (!isVisible(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.width > 72 || r.height > 72) continue;
        const text = (el.innerText || el.textContent || '').trim();
        const aria = (el.getAttribute?.('aria-label') || '').toLowerCase();
        const cls = (el.className || '').toString().toLowerCase();
        const nearTopRight = r.right >= topRight.right - 120 && r.top <= topRight.top + 100;
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
        return { clicked: true, method: 'top_right_candidate' };
    }
    return { clicked: false, method: 'not_found' };
}
const kind = arguments[0] || '';
const modal = findModal(kind);
if (!modal) return { present: false, clicked: false, kind };
const out = clickCloseOnModal(modal);
out.present = true;
out.kind = kind;
return out;
"""

_DETECT_MODAL_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden';
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
const body = document.body?.innerText || '';
const compact = norm(body);
const kind = arguments[0] || '';
if (kind === 'image_space') {
    return compact.includes('图片空间') && (compact.includes('确认') || compact.includes('全部文件'));
}
if (kind === 'post_publish') {
    return (compact.includes('待处理') && (compact.includes('去设置') || compact.includes('立即参与')))
        || compact.includes('发布成功')
        || compact.includes('商品发布成功');
}
return false;
"""


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def _modal_visible(page: DpPage, kind: str) -> bool:
    try:
        return bool(page.run_js(_DETECT_MODAL_JS, kind))
    except Exception:
        return False


def _attempt_dismiss(page: DpPage, kind: str) -> dict[str, Any]:
    try:
        raw = page.run_js(_CLICK_MODAL_CLOSE_JS, kind)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def dismiss_image_space_modal(page: DpPage, account_id: str, label: str) -> bool:
    """分支 C 上传主图时弹出的「图片空间」：点右上角 X 关闭。"""
    if not _modal_visible(page, "image_space"):
        return False
    info = _attempt_dismiss(page, "image_space")
    if info.get("clicked"):
        _log(
            account_id,
            label,
            f"已关闭「图片空间」弹窗（{info.get('method', 'close')}）",
        )
        time.sleep(0.6)
        return True
    _log(account_id, label, "检测到「图片空间」弹窗，但未点到关闭按钮")
    return False


def ensure_image_space_modal_cleared(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_attempts: int = 3,
) -> bool:
    """循环尝试关闭图片空间弹窗。"""
    cleared = True
    for attempt in range(max_attempts):
        if not _modal_visible(page, "image_space"):
            return cleared
        cleared = False
        if dismiss_image_space_modal(page, account_id, label):
            cleared = True
            continue
        time.sleep(0.5)
    return not _modal_visible(page, "image_space")


def dismiss_post_publish_goods_list_modal(
    page: DpPage,
    account_id: str,
    label: str,
) -> bool:
    """
    上架成功等待后回到商品列表/主界面时弹出的遮罩（如「待处理」「发布成功」）。
    点弹窗右上角 X 关闭。
    """
    if not _modal_visible(page, "post_publish"):
        return False
    info = _attempt_dismiss(page, "post_publish")
    if info.get("clicked"):
        _log(
            account_id,
            label,
            f"已关闭上架后提示弹窗（{info.get('method', 'close')}）",
        )
        time.sleep(0.6)
        return True
    _log(account_id, label, "检测到上架后提示弹窗，但未点到关闭按钮")
    return False


def ensure_post_publish_modals_cleared(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_attempts: int = 4,
) -> bool:
    """提交成功等待结束后、核验商品列表前调用。"""
    for _ in range(max_attempts):
        if not _modal_visible(page, "post_publish"):
            return True
        dismiss_post_publish_goods_list_modal(page, account_id, label)
        time.sleep(0.4)
    return not _modal_visible(page, "post_publish")

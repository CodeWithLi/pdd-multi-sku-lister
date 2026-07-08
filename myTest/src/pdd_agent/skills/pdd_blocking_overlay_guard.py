"""
拼多多商家后台：统一关闭「可安全忽略」的遮罩弹窗。

仅处理运营/待办/通知类弹窗（待处理、经营地址、发布成功等），
业务必需弹窗（推荐分类、下架确认、选择商品等）一律跳过。

现有各步骤内的专用 dismiss 逻辑保持不变；本模块作为额外清场守卫，
在页面跳转、点击等基础设施点被调用。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

# 业务弹窗特征：命中则绝不自动关
_BUSINESS_PROTECTED_MARKERS: tuple[str, ...] = (
    "推荐分类",
    "为您推荐分类",
    "根据您上传的图片",
    "确定下架",
    "确认下架",
    "下架所选",
    "选择商品",
    "确定离开",
    "放弃编辑",
    "继续编辑",
    "离开页面",
    "创建推广",
    "充值推广",
    "限时限量",
    "规格预览",
    "批量设置",
)

# 可安全点 X 关闭的弹窗特征
_SAFE_DISMISS_MARKERS: tuple[str, ...] = (
    "待处理",
    "去设置",
    "立即参与",
    "立即配置",
    "经营地址",
    "联系/经营地址",
    "登记实际经营",
    "确认补充",
    "去补充",
    "发布成功",
    "商品发布成功",
    "售罄提醒",
    "新消息",
    "查看全部",
    "通知",
    "合规",
    "外部平台",
)

_DISMISS_GENERIC_SAFE_MODAL_JS = """
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
            || cur.getAttribute?.('data-testid') === 'beast-core-icon-close') {
            return cur;
        }
        cur = cur.parentElement;
    }
    return el;
}
const businessMarkers = arguments[0] || [];
const safeMarkers = arguments[1] || [];
const includeImageSpace = !!arguments[2];

function isBusinessProtected(text) {
    const c = norm(text);
    if (!c) return false;
    if (c.includes('推荐分类') && (c.includes('请选择') || c.includes('为您推荐') || c.includes('根据您上传'))) {
        return true;
    }
    return businessMarkers.some((m) => c.includes(norm(m)));
}
function isSafeDismiss(text) {
    const c = norm(text);
    if (!c) return false;
    if (includeImageSpace
        && c.includes('图片空间')
        && (c.includes('确认') || c.includes('取消') || c.includes('全部文件'))) {
        return true;
    }
    return safeMarkers.some((m) => c.includes(norm(m)));
}
function findModalRoots() {
    const selectors = [
        '[data-testid="beast-core-modal"]',
        '[class*="beast-core-modal"]',
        '[class*="MDL_modal"]',
        '[role="dialog"]',
        '[class*="modal"]',
        '[class*="Modal"]',
        '[class*="PersonalShopBusinessAddressModifyModal"]',
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
function clickCloseOnModal(modalRoot) {
    if (!modalRoot) return { clicked: false, method: 'no_root' };
    const scope = modalRoot === document.body ? document : modalRoot;
    const exact = scope.querySelector?.('[data-testid="beast-core-icon-close"]')
        || Array.from(scope.querySelectorAll(
            '[data-testid="beast-core-icon-close"], [class*="closeIcon"], [class*="CloseIcon"], '
            + '[class*="modal-close"], [aria-label="Close"], [aria-label="关闭"]'
        )).find(isVisible);
    if (exact) {
        clickable(exact).click();
        return { clicked: true, method: 'close_icon' };
    }
    const modalRect = modalRoot.getBoundingClientRect?.()
        || { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    const useRect = modalRect.right > 100 ? modalRect : {
        left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight,
    };
    const candidates = [];
    for (const el of scope.querySelectorAll('button, a, span, i, svg, div')) {
        if (!isVisible(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.width > 72 || r.height > 72) continue;
        const text = (el.innerText || el.textContent || '').trim();
        const aria = (el.getAttribute?.('aria-label') || '').toLowerCase();
        const cls = (el.className || '').toString().toLowerCase();
        const nearTopRight = r.right >= useRect.right - 120 && r.top <= useRect.top + 100;
        const nearTopLeft = r.left <= useRect.left + 120 && r.top <= useRect.top + 100;
        if (!nearTopRight && !nearTopLeft) continue;
        if (
            text === '×' || text === '✕' || text === 'X'
            || aria.includes('close') || aria.includes('关闭')
            || cls.includes('close')
        ) {
            const score = nearTopRight ? -(r.right) + r.top : r.left + r.top;
            candidates.push({ el, score });
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
for (const root of roots) {
    const text = root.innerText || root.textContent || '';
    if (isBusinessProtected(text)) {
        return { acted: false, skipped: true, reason: 'business_protected', preview: norm(text).slice(0, 40) };
    }
}
for (const root of roots) {
    const text = root.innerText || root.textContent || '';
    if (!isSafeDismiss(text)) continue;
    const out = clickCloseOnModal(root);
    out.acted = !!out.clicked;
    out.source = 'generic_safe_modal';
    out.preview = norm(text).slice(0, 60);
    return out;
}
return { acted: false, present: roots.length > 0, reason: 'no_safe_modal' };
"""


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def _dismiss_via_existing_handlers(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    include_image_space: bool,
) -> dict[str, Any]:
    """复用现有专用 handler，行为与原先各步骤内调用一致。"""
    from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
        dismiss_image_space_modal,
        dismiss_post_publish_goods_list_modal,
    )

    if _try_address_dismiss(page, account_id, label):
        return {"acted": True, "source": "address_required"}

    if dismiss_post_publish_goods_list_modal(page, account_id, label):
        return {"acted": True, "source": "post_publish_pending"}

    if _try_message_popup_dismiss(page):
        return {"acted": True, "source": "message_popup"}

    if include_image_space and dismiss_image_space_modal(page, account_id, label):
        return {"acted": True, "source": "image_space"}

    return {"acted": False}


def _try_address_dismiss(page: DpPage, account_id: str, label: str) -> bool:
    try:
        from pdd_agent.skills.listing.upload import (
            _dismiss_address_required_page,
            _dismiss_business_address_registration_notice,
        )

        if _dismiss_business_address_registration_notice(page, account_id, label):
            return True
        return bool(_dismiss_address_required_page(page, account_id, label))
    except Exception:
        return False


def _try_message_popup_dismiss(page: DpPage) -> bool:
    try:
        from pdd_agent.skills.campaign.limited_time import _dismiss_message_popup

        before = page.run_js(
            """
            const t = document.body?.innerText || '';
            return t.includes('新消息') && t.includes('查看全部');
            """
        )
        if not before:
            return False
        _dismiss_message_popup(page)
        return True
    except Exception:
        return False


def _dismiss_generic_safe_modal(
    page: DpPage,
    *,
    include_image_space: bool,
) -> dict[str, Any]:
    try:
        raw = page.run_js(
            _DISMISS_GENERIC_SAFE_MODAL_JS,
            list(_BUSINESS_PROTECTED_MARKERS),
            list(_SAFE_DISMISS_MARKERS),
            include_image_space,
        )
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def clear_one_pdd_blocking_overlay(
    page: DpPage,
    account_id: str = "",
    label: str = "",
    *,
    include_image_space: bool = False,
) -> dict[str, Any]:
    """
    尝试关闭一个遮挡弹窗。
    先走现有专用 handler，再走通用安全弹窗识别。
    """
    result = _dismiss_via_existing_handlers(
        page,
        account_id,
        label,
        include_image_space=include_image_space,
    )
    if result.get("acted"):
        return result

    generic = _dismiss_generic_safe_modal(
        page, include_image_space=include_image_space
    )
    if generic.get("skipped"):
        return generic
    if generic.get("acted"):
        _log(
            account_id,
            label,
            f"守卫：已关闭遮挡弹窗（{generic.get('method', 'close')}，"
            f"{generic.get('preview', '')[:30]}）",
        )
        time.sleep(0.5)
        return generic
    return {"acted": False, **generic}


def ensure_pdd_blocking_overlays_cleared(
    page: DpPage,
    account_id: str = "",
    label: str = "",
    *,
    max_attempts: int = 5,
    include_image_space: bool = False,
) -> bool:
    """
    循环清理可安全关闭的遮罩，用于页面跳转后或关键点击前。
    默认不处理「图片空间」（避免干扰上传选图流程）。
    """
    dismissed = 0
    for _ in range(max(1, max_attempts)):
        result = clear_one_pdd_blocking_overlay(
            page,
            account_id,
            label,
            include_image_space=include_image_space,
        )
        if result.get("skipped"):
            return True
        if not result.get("acted"):
            break
        dismissed += 1
        time.sleep(0.35)

    if dismissed:
        _log(account_id, label, f"守卫：共关闭 {dismissed} 层遮挡弹窗")
    return True

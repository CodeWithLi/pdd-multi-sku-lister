"""分支 C：分类页/下一步跳转阶段遮挡弹窗（如「图片空间」）关闭。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

from pdd_agent.skills.listing.category_page_flow import CategoryPageMode

_DISMISS_IMAGE_SPACE_HINT_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) { return (t || '').replace(/\\s+/g, ''); }
function contextText(el) {
    let cur = el;
    for (let i = 0; i < 8 && cur; i++) {
        const t = cur.innerText || cur.textContent || '';
        if (norm(t).includes('仅展示可用图片')) return t;
        cur = cur.parentElement;
    }
    return '';
}
for (const el of document.querySelectorAll('button, a, span, div')) {
    if (!isVisible(el)) continue;
    const text = (el.innerText || el.textContent || '').trim();
    if (text !== '我知道了' && text !== '知道了') continue;
    const ctx = contextText(el);
    if (!norm(ctx).includes('仅展示可用图片')) continue;
    el.click();
    return { clicked: true, method: 'image_space_hint' };
}
return { clicked: false, method: 'no_hint' };
"""


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def dismiss_branch_c_image_space_hint_tooltip(page: DpPage) -> bool:
    """关闭「仅展示可用图片」引导气泡上的「我知道了」。"""
    try:
        raw = page.run_js(_DISMISS_IMAGE_SPACE_HINT_JS)
        return bool(isinstance(raw, dict) and raw.get("clicked"))
    except Exception:
        return False


def ensure_branch_c_blocking_overlays_cleared(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_attempts: int = 2,
) -> bool:
    """
    分支 C：关闭可能挡住「下一步」或页面跳转的弹层。
    优先关引导气泡，再关「图片空间」右上角 X。
    """
    from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
        ensure_image_space_modal_cleared,
    )
    from pdd_agent.skills.pdd_blocking_overlay_guard import (
        ensure_pdd_blocking_overlays_cleared,
    )

    ensure_pdd_blocking_overlays_cleared(
        page, account_id, label, max_attempts=2, include_image_space=False
    )

    if dismiss_branch_c_image_space_hint_tooltip(page):
        _log(account_id, label, "分支 C：已关闭「仅展示可用图片」引导")
        time.sleep(0.35)

    return ensure_image_space_modal_cleared(
        page, account_id, label, max_attempts=max_attempts
    )


def clear_branch_c_overlays_before_category_next(
    page: DpPage,
    account_id: str,
    label: str,
) -> None:
    """点「下一步」前清理遮挡弹层。"""
    if ensure_branch_c_blocking_overlays_cleared(
        page, account_id, label, max_attempts=2
    ):
        return
    ensure_branch_c_blocking_overlays_cleared(
        page, account_id, label, max_attempts=1
    )


def wait_branch_c_category_page_advance(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_wait: int,
    mode: CategoryPageMode = "render_wait",
    ui_type: str = "C",
) -> bool:
    """
    分支 C 专用：监听分类页跳转，期间持续尝试关闭「图片空间」等遮挡。
    """
    from pdd_agent.skills.listing import upload as listing_upload

    if ui_type != "C":
        return listing_upload._wait_for_category_page_advance(
            page,
            account_id,
            label,
            max_wait=max_wait,
            mode=mode,
            ui_type=ui_type,
        )

    if not listing_upload._is_still_on_category_publish_step(page):
        return True

    print(
        f"[{account_id}] [{label}] 继续监听页面跳转，最多 {max_wait}s…",
        flush=True,
    )
    for sec in range(max_wait):
        time.sleep(1)
        ensure_branch_c_blocking_overlays_cleared(
            page, account_id, label, max_attempts=1
        )
        if not listing_upload._is_still_on_category_publish_step(page):
            print(
                f"[{account_id}] [{label}] 已跳转到完善商品信息页 ({sec + 1}s)",
                flush=True,
            )
            return True
        if (sec + 1) % 10 == 0:
            print(
                f"[{account_id}] [{label}] 仍在等待页面跳转… ({sec + 1}/{max_wait}s)",
                flush=True,
            )
            ensure_branch_c_blocking_overlays_cleared(
                page, account_id, label, max_attempts=2
            )
            if mode == "manual_picker":
                listing_upload._confirm_category_picker_selection(
                    page, account_id, label
                )
            else:
                listing_upload._click_branch_c_category_recommendation(
                    page, account_id, label
                )
            listing_upload._dismiss_category_search_overlay(
                page, account_id, label
            )
            clear_branch_c_overlays_before_category_next(
                page, account_id, label
            )
            listing_upload._click_branch_c_category_next(
                page, account_id, label
            )

    advanced = not listing_upload._is_still_on_category_publish_step(page)
    if not advanced:
        print(
            f"[{account_id}] [{label}] 等待跳转超时 ({max_wait}s)，仍在分类页",
            flush=True,
        )
    return advanced

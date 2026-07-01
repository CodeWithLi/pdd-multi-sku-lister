"""分支 C 分类页「下一步，完善商品信息」按钮点击（e2e-publish-button）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

BRANCH_C_NEXT_SELECTORS: tuple[str, ...] = (
    'css:button[data-e2e-id="e2e-publish-button"]',
    'css:[data-e2e-id="e2e-publish-button"]',
    'css:button[data-testid="beast-core-button"]',
    "#bottomSubmitBtnId",
    "text:下一步，完善商品信息",
)

_RESOLVE_BRANCH_C_NEXT_POINT_JS = """
function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 20 && r.height > 20
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) {
    return (t || '').replace(/\\s+/g, '');
}
function pick(el, method) {
    if (!el || !isVisible(el)) return null;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    const r = el.getBoundingClientRect();
    return {
        x: r.left + r.width / 2,
        y: r.top + r.height / 2,
        method,
        id: el.id || '',
        e2e: el.getAttribute('data-e2e-id') || '',
        w: r.width,
        h: r.height,
    };
}
const byE2e = document.querySelector('[data-e2e-id="e2e-publish-button"]');
const fromE2e = pick(byE2e, 'e2e-publish-button');
if (fromE2e) return fromE2e;
const byId = document.getElementById('bottomSubmitBtnId');
const fromId = pick(byId, 'bottomSubmitBtnId');
if (fromId) return fromId;
for (const el of document.querySelectorAll('button[data-testid="beast-core-button"], button')) {
    const t = norm(el.innerText || el.textContent || '');
    if (!t.includes('下一步') || !t.includes('完善商品信息')) continue;
    if (!isVisible(el)) continue;
    const pt = pick(el, 'beast-core-button');
    if (pt) return pt;
}
return null;
"""


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def log_branch_c_next_diagnostics(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    from pdd_agent.skills.listing import upload as listing_upload

    info: dict[str, Any] = {"selectors": {}}
    for sel in BRANCH_C_NEXT_SELECTORS:
        el = page.ele(sel, timeout=0.4)
        info["selectors"][sel] = bool(el)
    try:
        point = page.run_js(_RESOLVE_BRANCH_C_NEXT_POINT_JS)
        if isinstance(point, dict):
            info["point"] = point
    except Exception as exc:
        info["js_error"] = str(exc)
    state = listing_upload._read_category_submit_state(page)
    info["submit_state"] = {
        "visible": state.get("visible"),
        "disabled": state.get("disabled"),
        "ready": state.get("ready"),
    }
    pt = info.get("point") or {}
    _log(
        account_id,
        label,
        "分支 C 下一步按钮诊断："
        f"e2e={info['selectors'].get('css:button[data-e2e-id=\"e2e-publish-button\"]')} "
        f"method={pt.get('method', '')} size={pt.get('w', 0)}x{pt.get('h', 0)} "
        f"submit_visible={info['submit_state'].get('visible')}",
    )
    return info


def _scroll_to_next_button(page: DpPage) -> None:
    from pdd_agent.skills.listing import upload as listing_upload

    listing_upload._blur_page_focus(page)
    try:
        page.run_js(
            """
            const btn = document.querySelector('[data-e2e-id="e2e-publish-button"]')
                || document.getElementById('bottomSubmitBtnId');
            if (btn) {
                btn.scrollIntoView({ block: 'center', behavior: 'instant' });
            } else {
                window.scrollTo(0, document.body.scrollHeight);
            }
            """
        )
    except Exception:
        pass
    time.sleep(0.35)


def _click_via_playwright_locator(page: DpPage, selector: str) -> bool:
    from pdd_agent.skills.listing import upload as listing_upload

    raw = getattr(page, "_page", None)
    if raw is None:
        return False
    pw_sel = selector
    if pw_sel.startswith("css:"):
        pw_sel = pw_sel[4:]
    elif pw_sel.startswith("text:"):
        try:
            loc = raw.get_by_text(pw_sel[5:], exact=False)
            loc.first.wait_for(state="visible", timeout=2000)
            listing_upload._playwright_mouse_click_element(page, page.ele(selector, timeout=1))
            return True
        except Exception:
            return False
    try:
        loc = raw.locator(pw_sel).first
        loc.wait_for(state="visible", timeout=2000)
        loc.scroll_into_view_if_needed(timeout=2000)
        box = loc.bounding_box(timeout=2000)
        if box and listing_upload._playwright_mouse_at(
            page,
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2,
        ):
            return True
        loc.click(timeout=3000)
        return True
    except Exception:
        return False


def click_branch_c_category_next_button(
    page: DpPage,
    account_id: str,
    label: str,
) -> tuple[bool, str]:
    """分支 C：优先 data-e2e-id=e2e-publish-button 点击下一步。"""
    from pdd_agent.skills.listing import upload as listing_upload
    from pdd_agent.skills.listing.category_branch_c_overlay_dismiss import (
        clear_branch_c_overlays_before_category_next,
    )

    clear_branch_c_overlays_before_category_next(page, account_id, label)
    listing_upload._dismiss_category_search_overlay(page, account_id, label)
    _scroll_to_next_button(page)

    for selector in BRANCH_C_NEXT_SELECTORS[:3]:
        if _click_via_playwright_locator(page, selector):
            short = selector.replace("css:", "")
            _log(account_id, label, f"分支 C：已点击「下一步」({short})")
            return True, selector

    try:
        point = page.run_js(_RESOLVE_BRANCH_C_NEXT_POINT_JS)
    except Exception:
        point = None
    if isinstance(point, dict) and point.get("x") and point.get("y"):
        method = str(point.get("method") or "js-point")
        if listing_upload._playwright_mouse_at(page, float(point["x"]), float(point["y"])):
            _log(account_id, label, f"分支 C：已坐标点击「下一步」(mouse/{method})")
            return True, f"mouse/{method}"

    for selector in BRANCH_C_NEXT_SELECTORS[3:]:
        btn = page.ele(selector, timeout=1)
        if btn and listing_upload._playwright_mouse_click_element(page, btn):
            _log(account_id, label, f"分支 C：已点击「下一步」({selector})")
            return True, selector

    log_branch_c_next_diagnostics(page, account_id, label)
    return False, ""

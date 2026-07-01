"""
分支 C + AI 标题页 — 选类完成后点「下一步」未跳转时的页面随机点击补救。

仅当 listing_info 标记了 AI 标题流程时使用；传统分支 C 页面仍走 upload._click_category_next_step_burst。

AI 标题简化页：平台需一次「人工式」表单激活 + Playwright trusted 鼠标点「下一步」
（首次 click 常仅唤醒校验，第二次才真正跳转）；避免 loc.click() 与反复点推荐类目。
"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

CategoryNextErr = Literal["", "not_found", "no_advance", "modal_blocking"]

NUDGE_CLICK_MIN = 3
NUDGE_CLICK_MAX = 5

_RESOLVE_TITLE_INPUT_POINT_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 40 && r.height > 12
        && r.bottom > 0 && r.right > 0
        && s.display !== 'none' && s.visibility !== 'hidden';
}
for (const sel of [
    'input[placeholder*="商品标题"]',
    'input[placeholder*="标题"]',
]) {
    const el = document.querySelector(sel);
    if (el && isVisible(el)) {
        const r = el.getBoundingClientRect();
        return { x: r.left + r.width * 0.35, y: r.top + r.height / 2, kind: 'title' };
    }
}
for (const el of document.querySelectorAll('input')) {
    if (!isVisible(el)) continue;
    const ph = el.getAttribute('placeholder') || '';
    if (!ph.includes('标题')) continue;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width * 0.35, y: r.top + r.height / 2, kind: 'title' };
}
return null;
"""

_RESOLVE_SELECTED_CATEGORY_TAP_JS = """
function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 40 && r.height > 20
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function isCategoryPath(text) {
    const t = (text || '').replace(/\\s+/g, ' ').trim();
    if (!t.includes('>')) return false;
    const parts = t.split('>').map(p => p.trim()).filter(Boolean);
    return parts.length >= 2 && t.length >= 10 && t.length <= 150;
}
function looksSelected(el) {
    if (!el) return false;
    const cls = (el.className || '').toString();
    if (/selected|Selected|active|checked|current|highlight/i.test(cls)) return true;
    const style = window.getComputedStyle(el);
    const border = style.borderColor || '';
    if (border && border !== 'rgba(0, 0, 0, 0)' && border !== 'transparent') {
        if (parseFloat(style.borderWidth || '0') >= 1) return true;
    }
    if (el.querySelector('svg, [class*="check"], [class*="Check"]')) return true;
    let node = el;
    for (let i = 0; i < 4 && node; i++) {
        const c = (node.className || '').toString();
        if (/selected|Selected|active|checked|current/i.test(c)) return true;
        node = node.parentElement;
    }
    return false;
}
function pointOf(el, label) {
    if (!el || !isVisible(el)) return null;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, text: label.slice(0, 60), kind: 'category' };
}
const candidates = [];
for (const el of document.querySelectorAll('div, li, span, button, a')) {
    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!isCategoryPath(t)) continue;
    if (!isVisible(el)) continue;
    const r = el.getBoundingClientRect();
    candidates.push({ el, t, score: r.width * r.height, selected: looksSelected(el) });
}
candidates.sort((a, b) => {
    if (a.selected !== b.selected) return a.selected ? -1 : 1;
    return a.score - b.score;
});
for (const item of candidates) {
    if (!item.selected) continue;
    const pt = pointOf(item.el, item.t);
    if (pt) return pt;
}
if (candidates.length) {
    const pt = pointOf(candidates[0].el, candidates[0].t);
    if (pt) return pt;
}
return null;
"""

_PICK_TARGETED_NUDGE_POINT_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 12 && r.height > 12
        && r.bottom > 0 && r.right > 0
        && r.top < window.innerHeight && r.left < window.innerWidth
        && s.display !== 'none' && s.visibility !== 'hidden';
}
function isCategoryPath(text) {
    const t = (text || '').replace(/\\s+/g, ' ').trim();
    return t.includes('>') && t.length >= 10 && t.length <= 150;
}
const points = [];
for (const sel of ['input[placeholder*="商品标题"]', 'input[placeholder*="标题"]']) {
    const el = document.querySelector(sel);
    if (el && isVisible(el)) {
        const r = el.getBoundingClientRect();
        points.push({ x: r.left + r.width * 0.4, y: r.top + r.height / 2, kind: 'title' });
        break;
    }
}
for (const el of document.querySelectorAll('div, span, button, li')) {
    if (!isVisible(el)) continue;
    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!isCategoryPath(t)) continue;
    const r = el.getBoundingClientRect();
    if (r.left < window.innerWidth * 0.28) continue;
    points.push({ x: r.left + r.width / 2, y: r.top + r.height / 2, kind: 'category', text: t.slice(0, 40) });
    break;
}
for (const el of document.querySelectorAll('div, section, label')) {
    if (!isVisible(el)) continue;
    const t = (el.innerText || el.textContent || '').slice(0, 30);
    if (t.includes('商品主图') || t.includes('商品分类')) {
        const r = el.getBoundingClientRect();
        if (r.left > window.innerWidth * 0.28) {
            points.push({
                x: r.left + r.width * 0.15,
                y: r.top + Math.min(r.height * 0.2, 24),
                kind: 'blank',
            });
            break;
        }
    }
}
if (points.length) return points[Math.floor(Math.random() * points.length)];
return null;
"""


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def branch_c_ai_title_nudge_enabled(
    listing_info: dict[str, Any] | None,
    page: DpPage,
) -> bool:
    """分支 C 且 AI 标题页（标题已填入）时才启用页面随机点击补救。"""
    from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
        branch_c_category_page_ai_title_applied,
        _listing_uses_page_ai_title_mode,
    )
    from pdd_agent.skills.listing.page_ai_title import _read_title_from_input

    info = listing_info or {}
    if not (
        branch_c_category_page_ai_title_applied(info)
        or _listing_uses_page_ai_title_mode(info)
    ):
        return False
    title = str(_read_title_from_input(page) or "").strip()
    return len(title) >= 2


def _mouse_at_point(page: DpPage, point: dict[str, Any]) -> bool:
    from pdd_agent.skills.listing import upload as listing_upload

    x = float(point.get("x") or 0)
    y = float(point.get("y") or 0)
    if x <= 0 or y <= 0:
        return False
    return listing_upload._playwright_mouse_at(page, x, y)


def prime_branch_c_ai_title_page_for_next(
    page: DpPage,
    account_id: str,
    label: str,
) -> None:
    """模拟人工：点标题失焦 + 轻点已选推荐类目，唤醒表单校验后再点下一步。"""
    from pdd_agent.skills.listing import upload as listing_upload

    listing_upload._blur_page_focus(page)
    try:
        title_pt = page.run_js(_RESOLVE_TITLE_INPUT_POINT_JS)
        if isinstance(title_pt, dict) and _mouse_at_point(page, title_pt):
            _log(account_id, label, "分支 C AI 标题页：激活表单（点标题输入框）")
            time.sleep(random.uniform(0.2, 0.35))
            listing_upload._blur_page_focus(page)
    except Exception:
        pass

    state = listing_upload._read_category_submit_state(page)
    if state.get("selectedPathReady"):
        try:
            cat_pt = page.run_js(_RESOLVE_SELECTED_CATEGORY_TAP_JS)
            if isinstance(cat_pt, dict) and _mouse_at_point(page, cat_pt):
                _log(
                    account_id,
                    label,
                    f"分支 C AI 标题页：激活表单（轻点已选类目）{cat_pt.get('text', '')}",
                )
                time.sleep(random.uniform(0.25, 0.45))
        except Exception:
            pass

    time.sleep(random.uniform(0.15, 0.3))


def _ensure_branch_c_category_for_ai_next(
    page: DpPage,
    account_id: str,
    label: str,
) -> None:
    """类目未就绪时点推荐；已选完整路径时不再反复点推荐（避免 toggle）。"""
    from pdd_agent.skills.listing import upload as listing_upload

    state = listing_upload._read_category_submit_state(page)
    if state.get("selectedPathReady"):
        return
    listing_upload._click_branch_c_category_recommendation(page, account_id, label)


def _single_trusted_next_click(page: DpPage) -> tuple[bool, str]:
    """仅 Playwright 坐标 mouse 点击「下一步」，不用 loc.click()。"""
    from pdd_agent.skills.listing import upload as listing_upload
    from pdd_agent.skills.listing.category_branch_c_next import (
        _RESOLVE_BRANCH_C_NEXT_POINT_JS,
        _scroll_to_next_button,
    )

    listing_upload._dismiss_category_search_overlay(page, "", "")
    _scroll_to_next_button(page)
    try:
        point = page.run_js(_RESOLVE_BRANCH_C_NEXT_POINT_JS)
    except Exception:
        point = None
    if isinstance(point, dict) and point.get("x") and point.get("y"):
        method = str(point.get("method") or "js-point")
        if listing_upload._playwright_mouse_at(page, float(point["x"]), float(point["y"])):
            return True, f"mouse/{method}"
    return False, ""


def click_branch_c_next_two_step_trusted(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    context: str = "",
    prime: bool = True,
) -> tuple[bool, str]:
    """
    两步 trusted 点击「下一步」：先激活表单，第一次点击常仅唤醒，第二次提交跳转。
    """
    from pdd_agent.skills.listing import upload as listing_upload

    ctx = f"{context} " if str(context or "").strip() else ""
    if prime:
        prime_branch_c_ai_title_page_for_next(page, account_id, label)

    last_method = ""
    for step, step_name in ((1, "唤醒"), (2, "提交")):
        ok, method = _single_trusted_next_click(page)
        if ok:
            last_method = method
            _log(
                account_id,
                label,
                f"分支 C AI 标题页：{ctx}第{step}次 trusted 点击「下一步」({step_name}) ({method})",
            )
        else:
            _log(account_id, label, f"分支 C AI 标题页：{ctx}第{step}次点击「下一步」失败")
            return False, last_method
        time.sleep(random.uniform(0.55, 0.95))
        if not listing_upload._is_still_on_category_publish_step(page):
            return True, last_method

    return True, last_method


def _pick_targeted_nudge_point(page: DpPage) -> dict[str, Any] | None:
    try:
        raw = page.run_js(_PICK_TARGETED_NUDGE_POINT_JS)
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def targeted_form_nudge_clicks_on_publish_page(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    count: int | None = None,
) -> int:
    """在标题/已选类目/表单空白处点击，模拟人工失焦（比随机坐标更稳）。"""
    from pdd_agent.skills.listing import upload as listing_upload

    total = count if count is not None else random.randint(NUDGE_CLICK_MIN, NUDGE_CLICK_MAX)
    total = max(2, min(NUDGE_CLICK_MAX, int(total)))
    clicked = 0
    for i in range(total):
        if not listing_upload._is_still_on_category_publish_step(page):
            break
        point = _pick_targeted_nudge_point(page)
        if not point:
            continue
        if _mouse_at_point(page, point):
            clicked += 1
            kind = point.get("kind") or "form"
            extra = f" {point.get('text', '')}" if point.get("text") else ""
            _log(
                account_id,
                label,
                f"分支 C AI 标题页：定向激活点击 ({i + 1}/{total}) [{kind}]{extra}",
            )
        time.sleep(random.uniform(0.3, 0.65))
    listing_upload._blur_page_focus(page)
    return clicked


def random_human_nudge_clicks_on_publish_page(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    count: int | None = None,
) -> int:
    """兼容旧名：AI 标题页改用定向表单点击。"""
    return targeted_form_nudge_clicks_on_publish_page(
        page, account_id, label, count=count
    )


def click_branch_c_category_next_with_recommendation(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    context: str = "",
) -> bool:
    """确保类目 + 两步 trusted 点「下一步」，并记录是否跳转。"""
    from pdd_agent.skills.listing import upload as listing_upload

    ctx = f"{context} " if str(context or "").strip() else ""
    listing_upload._dismiss_category_search_overlay(page, account_id, label)
    _ensure_branch_c_category_for_ai_next(page, account_id, label)
    ok, method = click_branch_c_next_two_step_trusted(
        page,
        account_id,
        label,
        context=ctx.rstrip(),
        prime=True,
    )
    if ok:
        if listing_upload._is_still_on_category_publish_step(page):
            _log(
                account_id,
                label,
                f"分支 C AI 标题页：{ctx}已成功点击「下一步」({method})，页面尚未跳转",
            )
        else:
            _log(
                account_id,
                label,
                f"分支 C AI 标题页：{ctx}已成功点击「下一步」({method})，页面已跳转",
            )
    else:
        _log(account_id, label, f"分支 C AI 标题页：{ctx}点击「下一步」失败")
    return ok


def nudge_then_retry_branch_c_category_next(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    nudge_count: int | None = None,
) -> bool:
    """定向激活表单后，再两步 trusted 点「下一步」。"""
    from pdd_agent.skills.listing import upload as listing_upload

    if not listing_upload._is_still_on_category_publish_step(page):
        return True
    count = nudge_count if nudge_count is not None else random.randint(NUDGE_CLICK_MIN, NUDGE_CLICK_MAX)
    _log(
        account_id,
        label,
        f"分支 C AI 标题页：下一步未跳转，先定向激活表单 {count} 次再重试",
    )
    targeted_form_nudge_clicks_on_publish_page(
        page, account_id, label, count=count
    )
    if not listing_upload._is_still_on_category_publish_step(page):
        return True
    return click_branch_c_category_next_with_recommendation(
        page, account_id, label, context="激活后"
    )


def wait_branch_c_category_advance_with_ai_nudge(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any],
    *,
    max_wait: int = 30,
) -> bool:
    """等待跳转；每 10s 仍卡住则「定向激活 + 重试下一步」。"""
    from pdd_agent.skills.listing import upload as listing_upload

    if not listing_upload._is_still_on_category_publish_step(page):
        return True

    _log(account_id, label, f"分支 C AI 标题页：继续监听页面跳转，最多 {max_wait}s…")
    from pdd_agent.skills.listing.category_branch_c_overlay_dismiss import (
        ensure_branch_c_blocking_overlays_cleared,
    )

    for sec in range(max_wait):
        time.sleep(1)
        ensure_branch_c_blocking_overlays_cleared(
            page, account_id, label, max_attempts=1
        )
        if not listing_upload._is_still_on_category_publish_step(page):
            _log(account_id, label, f"分支 C AI 标题页：已跳转到详情页 ({sec + 1}s)")
            return True
        if (sec + 1) % 10 == 0:
            _log(
                account_id,
                label,
                f"分支 C AI 标题页：仍在等待跳转 ({sec + 1}/{max_wait}s)，定向激活后重试下一步",
            )
            ensure_branch_c_blocking_overlays_cleared(
                page, account_id, label, max_attempts=2
            )
            nudge_then_retry_branch_c_category_next(page, account_id, label)

    advanced = not listing_upload._is_still_on_category_publish_step(page)
    if not advanced:
        _log(account_id, label, f"分支 C AI 标题页：等待跳转超时 ({max_wait}s)")
    return advanced


def advance_branch_c_category_after_ai_title_selection(
    page: DpPage,
    account_id: str,
    label: str,
    listing_info: dict[str, Any],
    *,
    category_mode: str = "render_wait",
) -> tuple[bool, CategoryNextErr]:
    """
    AI 标题页选类完成后点下一步：
    1. 激活表单 + 两步 trusted 点「下一步」
    2. 未跳转 → 定向激活 → 再重试（可重复 1 轮）
    3. 监听跳转（等待阶段每 10s 再 nudge + 下一步）
    """
    from pdd_agent.skills.listing import upload as listing_upload
    from pdd_agent.skills.listing.category_page_flow import DEFAULT_CATEGORY_ADVANCE_WAIT_BURST

    if not branch_c_ai_title_nudge_enabled(listing_info, page):
        return False, "not_found"

    listing_upload._wait_category_submit_ready(page, account_id, label)
    listing_upload._dismiss_category_search_overlay(page, account_id, label)

    _log(
        account_id,
        label,
        "分支 C AI 标题页：类目已选，两步 trusted 点「下一步」（未跳转则定向激活后重试）",
    )
    if not click_branch_c_category_next_with_recommendation(
        page, account_id, label, context="首次"
    ):
        return False, "not_found"
    if not listing_upload._is_still_on_category_publish_step(page):
        _log(account_id, label, "分支 C AI 标题页：首次点击「下一步」后页面已跳转")
        return True, ""

    for round_index in range(2):
        if not listing_upload._is_still_on_category_publish_step(page):
            return True, ""
        nudge_then_retry_branch_c_category_next(page, account_id, label)
        if not listing_upload._is_still_on_category_publish_step(page):
            _log(
                account_id,
                label,
                f"分支 C AI 标题页：定向激活后第 {round_index + 1} 次「下一步」已跳转",
            )
            return True, ""

    if not wait_branch_c_category_advance_with_ai_nudge(
        page,
        account_id,
        label,
        listing_info,
        max_wait=DEFAULT_CATEGORY_ADVANCE_WAIT_BURST,
    ):
        return False, "no_advance"
    return True, ""

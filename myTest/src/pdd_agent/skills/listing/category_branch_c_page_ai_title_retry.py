"""
分支 C + page_ai 标题 — 上传主图后轮询/重试点击「立即使用」。

场景：AI 推荐栏晚于首次检测出现，或文案为「AI/智能推荐标题」等变体，
若误走「page_ai 不在此等待」会导致未填标题 → 简化页选类失败 → category_next_step_not_found。

仅作用于 title_mode=page_ai；传统分支 C 不受影响。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

DEFAULT_INITIAL_WAIT = 2
DEFAULT_MAX_WAIT = 35
DEFAULT_POLL_INTERVAL = 1

_DETECT_AI_TITLE_BAR_JS = """
function norm(t) {
    return (t || '').replace(/\\s+/g, '');
}
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
const body = document.body.innerText || '';
const compact = norm(body);
const markers = [
    'AI智能推荐标题',
    'AI/智能推荐标题',
    'AI智能推荐',
    '智能推荐标题',
];
let variant = '';
for (const m of markers) {
    if (compact.includes(norm(m))) {
        variant = m;
        break;
    }
}
const fuzzyBar = !variant
    && compact.includes('立即使用')
    && (compact.includes('智能推荐') || compact.includes('AI生成'));
if (!variant && fuzzyBar) {
    variant = 'fuzzy_ai_bar';
}
let hasUseNow = false;
for (const n of document.querySelectorAll('a, span, button, div')) {
    const t = (n.innerText || n.textContent || '').trim();
    if (t !== '立即使用' || !isVisible(n)) continue;
    hasUseNow = true;
    break;
}
return {
    visible: !!variant,
    variant,
    hasUseNow,
    fuzzyBar: !!fuzzyBar,
};
"""


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def is_branch_c_page_ai_title_listing(product_info: dict[str, Any] | None) -> bool:
    from pdd_agent.skills.listing.page_ai_title import is_page_ai_title_mode

    return is_page_ai_title_mode(product_info or {})


def detect_branch_c_ai_title_recommendation_bar(page: DpPage) -> dict[str, Any]:
    """检测分类页 AI 推荐标题栏（含「AI/智能推荐标题」等变体）。"""
    from pdd_agent.skills.listing.page_ai_title import _find_use_now_button

    info: dict[str, Any] = {
        "visible": False,
        "variant": "",
        "hasUseNow": False,
        "fuzzyBar": False,
    }
    try:
        raw = page.run_js(_DETECT_AI_TITLE_BAR_JS)
        if isinstance(raw, dict):
            info.update(raw)
    except Exception:
        pass
    if not info.get("visible"):
        for text_marker in ("AI/智能推荐标题", "AI智能推荐标题", "AI智能推荐"):
            try:
                if page.ele(f"text:{text_marker}", timeout=0.35):
                    info["visible"] = True
                    info["variant"] = text_marker
                    break
            except Exception:
                continue
    if not info.get("hasUseNow"):
        try:
            info["hasUseNow"] = bool(_find_use_now_button(page))
        except Exception:
            pass
    if info.get("hasUseNow") and not info.get("visible"):
        info["visible"] = True
        info["variant"] = info.get("variant") or "use_now_only"
    return info


def branch_c_category_page_ai_title_bar_visible(page: DpPage) -> bool:
    """供 page_ai_title 模块复用：AI 推荐栏是否可见。"""
    bar = detect_branch_c_ai_title_recommendation_bar(page)
    return bool(bar.get("visible") or bar.get("hasUseNow"))


def _try_apply_use_now_once(page: DpPage, account_id: str, label: str) -> bool:
    from pdd_agent.skills.listing.page_ai_title import (
        _click_use_now_via_js,
        _find_use_now_button,
        _read_title_from_input,
    )

    use_btn = _find_use_now_button(page)
    if use_btn:
        try:
            page.run_js('arguments[0].scrollIntoView({block:"center"});', use_btn)
            use_btn.click()
        except Exception:
            if not _click_use_now_via_js(page):
                return False
    elif not _click_use_now_via_js(page):
        return False
    time.sleep(1.2)
    if _read_title_from_input(page):
        return True
    time.sleep(1.0)
    return bool(_read_title_from_input(page))


def retry_apply_branch_c_page_ai_title(
    page: DpPage,
    account_id: str,
    product_info: dict[str, Any],
    resolved_title: str = "",
    *,
    label: str = "",
    initial_wait: int = DEFAULT_INITIAL_WAIT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> tuple[str, bool]:
    """
    page_ai 专用：轮询等待 AI 栏出现，点击「立即使用」/「AI生成」，直到标题填入或超时。
    返回 (title, applied)。
    """
    from pdd_agent.skills.listing.page_ai_title import (
        _read_title_from_input,
        _try_click_ai_generate_title,
        wait_and_apply_page_ai_title,
    )

    if not is_branch_c_page_ai_title_listing(product_info):
        return "", False

    existing = str(_read_title_from_input(page) or "").strip()
    if existing:
        _log(account_id, label, f"分支 C page_ai：标题已就绪 → {existing[:60]}")
        return existing, True

    _log(
        account_id,
        label,
        f"分支 C page_ai：轮询等待 AI 推荐栏并点击「立即使用」（最多 {max_wait}s）",
    )
    time.sleep(max(0, int(initial_wait)))

    ai_generate_tried = False
    for sec in range(max_wait):
        existing = str(_read_title_from_input(page) or "").strip()
        if existing:
            _log(account_id, label, f"分支 C page_ai：标题已填入 → {existing[:60]}")
            return existing, True

        bar = detect_branch_c_ai_title_recommendation_bar(page)
        if bar.get("visible") or bar.get("hasUseNow"):
            variant = str(bar.get("variant") or "ai_bar")
            _log(
                account_id,
                label,
                f"分支 C page_ai：检测到 AI 推荐栏（{variant}），点击「立即使用」",
            )
            if _try_apply_use_now_once(page, account_id, label):
                existing = str(_read_title_from_input(page) or "").strip()
                if existing:
                    _log(account_id, label, f"分支 C page_ai：「立即使用」成功 → {existing[:60]}")
                    return existing, True
                _log(account_id, label, "分支 C page_ai：已点「立即使用」但标题仍空，继续等待…")

        if not ai_generate_tried and sec >= 3:
            ai_generate_tried = True
            from pdd_agent.skills.listing.page_ai_title import (
                try_apply_branch_c_ai_title_generate_dropdown,
            )

            generated = str(
                try_apply_branch_c_ai_title_generate_dropdown(
                    page, account_id, label=label, max_wait=10
                )
                or _try_click_ai_generate_title(page, account_id)
                or ""
            ).strip()
            if generated:
                _log(account_id, label, f"分支 C page_ai：「AI生成标题」成功 → {generated[:60]}")
                return generated, True

        if sec == 0 or (sec + 1) % 5 == 0:
            _log(
                account_id,
                label,
                f"分支 C page_ai：等待 AI 推荐栏… ({sec + 1}/{max_wait}s)",
            )
        time.sleep(poll_interval)

    existing = str(_read_title_from_input(page) or "").strip()
    if existing:
        return existing, True

    bar = detect_branch_c_ai_title_recommendation_bar(page)
    if bar.get("visible") or bar.get("hasUseNow"):
        try:
            title = wait_and_apply_page_ai_title(
                page,
                account_id,
                initial_wait=0,
                max_wait=12,
            )
            if str(title or "").strip():
                return str(title).strip(), True
        except RuntimeError:
            existing = str(_read_title_from_input(page) or "").strip()
            if existing:
                return existing, True

    existing = str(_read_title_from_input(page) or "").strip()
    if existing:
        return existing, True

    fallback = str(resolved_title or "").strip()
    _log(
        account_id,
        label,
        "分支 C page_ai：超时仍未填入 AI 标题，后续将尝试选类前补救",
    )
    return fallback, False


def ensure_branch_c_page_ai_title_before_category(
    page: DpPage,
    account_id: str,
    product_info: dict[str, Any],
    listing_info: dict[str, Any],
    *,
    label: str = "",
    max_wait: int = 20,
) -> tuple[str, bool]:
    """
    选类门禁前的二次补救：page_ai 且标题仍空、但 AI 栏已出现时再重试一轮。
    成功时写回 listing_info 标题与 meta 标记。
    """
    from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
        META_KEY_CATEGORY_AI_APPLIED,
    )
    from pdd_agent.skills.listing.page_ai_title import _read_title_from_input

    if not is_branch_c_page_ai_title_listing(product_info):
        return str(listing_info.get("title") or "").strip(), False

    existing = str(_read_title_from_input(page) or "").strip()
    if existing:
        listing_info["title"] = existing
        listing_info[META_KEY_CATEGORY_AI_APPLIED] = True
        return existing, True

    bar = detect_branch_c_ai_title_recommendation_bar(page)
    if not (bar.get("visible") or bar.get("hasUseNow")):
        return str(listing_info.get("title") or "").strip(), False

    _log(
        account_id,
        label,
        "分支 C page_ai：选类前补救 — AI 栏已出现但标题未填，重试「立即使用」",
    )
    title, applied = retry_apply_branch_c_page_ai_title(
        page,
        account_id,
        product_info,
        str(listing_info.get("title") or ""),
        label=label,
        initial_wait=0,
        max_wait=max_wait,
    )
    if applied and title:
        listing_info["title"] = title
        listing_info[META_KEY_CATEGORY_AI_APPLIED] = True
        return title, True

    existing = str(_read_title_from_input(page) or "").strip()
    if existing:
        listing_info["title"] = existing
        listing_info[META_KEY_CATEGORY_AI_APPLIED] = True
        return existing, True
    return str(listing_info.get("title") or "").strip(), False

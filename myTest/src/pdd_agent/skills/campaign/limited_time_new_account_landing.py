"""
限时限量购 — 新号无历史活动时的落地页兜底。

新号从营销工具进入限时限量购后，会落到 NoCurrentActivity 推广页（历史活动为空），
「立即创建」为 div 而非老店管理页的 button；需单独识别并点击后才能进入活动设置页。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pdd_agent.browser.dp_compat_sync import DpPage

_DETECT_NEW_LANDING_JS = """
() => {
    function isVisible(el) {
        if (!el || !el.getBoundingClientRect) return false;
        const r = el.getBoundingClientRect();
        const s = window.getComputedStyle(el);
        return r.width > 4 && r.height > 4
            && s.display !== 'none'
            && s.visibility !== 'hidden'
            && parseFloat(s.opacity || '1') > 0.05;
    }

    function normalizedText(el) {
        return String(el?.innerText || el?.textContent || '').replace(/\\s+/g, '');
    }

    const bodyText = normalizedText(document.body);

    if (
        bodyText.includes('活动设置')
        && (bodyText.includes('活动类型') || bodyText.includes('选择商品'))
    ) {
        return { match: false, reason: 'already_on_activity_settings' };
    }

    const legacyButton = document.querySelector('button[data-tracking-click-viewid="ele-create"]');
    if (legacyButton && isVisible(legacyButton)) {
        return { match: false, reason: 'legacy_ele_create_button' };
    }

    const legacyTabMarkers = ['活动商品', '进行中', '待开始', '已结束'];
    const legacyTabHits = legacyTabMarkers.filter((marker) => bodyText.includes(marker)).length;
    if (legacyTabHits >= 2) {
        return { match: false, reason: 'legacy_activity_product_tabs' };
    }

    const newLandingMarkers = [
        '历史活动',
        '暂无活动记录',
        '销量快速破零',
        '无需平台审核',
        '提升25%',
        '营销标签',
    ];
    const newLandingHits = newLandingMarkers.filter((marker) => bodyText.includes(marker)).length;

    const crtBtn = Array.from(
        document.querySelectorAll('[class*="NoCurrentActivity_crtBtn"], [class*="NoCurrentActivity_block"]')
    ).find((el) => isVisible(el) && normalizedText(el).includes('立即创建'));

    if (crtBtn) {
        return {
            match: true,
            reason: 'no_current_activity_button',
            newLandingHits,
        };
    }

    if (bodyText.includes('历史活动') && newLandingHits >= 1) {
        const createNodes = Array.from(document.querySelectorAll('div,button,a,span'))
            .filter((el) => {
                if (!isVisible(el)) return false;
                const text = String(el.innerText || el.textContent || '').trim();
                return text === '立即创建';
            });
        if (createNodes.length) {
            return {
                match: true,
                reason: 'history_activity_empty_landing',
                newLandingHits,
            };
        }
    }

    return { match: false, reason: 'not_new_account_landing' };
}
"""

_FIND_CREATE_TARGET_JS = """
() => {
    function isVisible(el) {
        if (!el || !el.getBoundingClientRect) return false;
        const r = el.getBoundingClientRect();
        const s = window.getComputedStyle(el);
        return r.width > 4 && r.height > 4
            && s.display !== 'none'
            && s.visibility !== 'hidden'
            && parseFloat(s.opacity || '1') > 0.05;
    }

    function normalizedText(el) {
        return String(el?.innerText || el?.textContent || '').trim();
    }

    function clickLikeUser(el) {
        const r = el.getBoundingClientRect();
        const x = r.left + Math.min(Math.max(20, r.width / 2), Math.max(20, r.width - 20));
        const y = r.top + Math.min(Math.max(20, r.height / 2), Math.max(20, r.height - 20));
        const target = document.elementFromPoint(x, y) || el;
        for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
            target.dispatchEvent(new MouseEvent(ev, {
                bubbles: true,
                cancelable: true,
                view: window,
                clientX: x,
                clientY: y,
            }));
        }
        if (target !== el) el.click();
    }

    const selectors = [
        '[class*="NoCurrentActivity_crtBtn"]',
        '[class*="NoCurrentActivity_button"] [class*="NoCurrentActivity_crtBtn"]',
        '[class*="NoCurrentActivity_innerBtnContainer"] [data-testid="beast-core-box"]',
    ];

    const candidates = [];
    for (const selector of selectors) {
        for (const el of Array.from(document.querySelectorAll(selector))) {
            if (!isVisible(el)) continue;
            if (!normalizedText(el).includes('立即创建')) continue;
            const rect = el.getBoundingClientRect();
            let score = rect.top * 10 + rect.left;
            if (String(el.className || '').includes('NoCurrentActivity_crtBtn')) score -= 100000;
            candidates.push({ el, rect, score, selector });
        }
    }

    if (!candidates.length) {
        for (const el of Array.from(document.querySelectorAll('div,button,a,span'))) {
            if (!isVisible(el)) continue;
            if (normalizedText(el) !== '立即创建') continue;
            const parentText = normalizedText(el.closest('[class*="NoCurrentActivity"]') || el.parentElement);
            if (!parentText.includes('历史活动') && !parentText.includes('销量快速破零')) continue;
            const rect = el.getBoundingClientRect();
            candidates.push({ el, rect, score: rect.top * 10 + rect.left, selector: 'fallback_text' });
        }
    }

    candidates.sort((a, b) => a.score - b.score);
    if (!candidates.length) {
        return { clicked: false, reason: 'create_button_not_found' };
    }

    const selected = candidates[0];
    clickLikeUser(selected.el);
    return {
        clicked: true,
        selector: selected.selector,
        rect: {
            left: Math.round(selected.rect.left),
            top: Math.round(selected.rect.top),
            width: Math.round(selected.rect.width),
            height: Math.round(selected.rect.height),
        },
    };
}
"""


def _safe_exc(exc: BaseException, limit: int = 300) -> str:
    msg = str(exc)
    if len(msg) > limit:
        msg = msg[:limit] + "..."
    return msg.encode("utf-8", errors="replace").decode("utf-8")


def detect_new_account_limited_time_landing(page: DpPage) -> dict[str, Any]:
    """检测是否为新号限时限量购落地页（NoCurrentActivity / 历史活动为空）。"""
    try:
        result = page.run_js(f"return ({_DETECT_NEW_LANDING_JS})();")
        if isinstance(result, dict):
            return result
    except Exception as exc:
        return {"match": False, "reason": "detect_error", "error": _safe_exc(exc)}
    return {"match": False, "reason": "invalid_detect_result"}


def is_new_account_limited_time_landing_page(page: DpPage) -> bool:
    return bool(detect_new_account_limited_time_landing(page).get("match"))


def click_new_account_landing_create(
    page: DpPage,
    account_id: str,
    *,
    dismiss_popup: Callable[[DpPage], None] | None = None,
    switch_to_latest_tab: Callable[[DpPage], bool] | None = None,
) -> bool:
    """在新号落地页点击中部「立即创建」，进入活动设置页。"""
    if dismiss_popup is not None:
        dismiss_popup(page)

    for attempt in range(1, 4):
        try:
            raw_page = getattr(page, "_page", None)
            if raw_page is not None:
                locator = raw_page.locator(
                    '[class*="NoCurrentActivity_crtBtn"]:has-text("立即创建"), '
                    '[class*="NoCurrentActivity_innerBtnContainer"] '
                    '[data-testid="beast-core-box"]:has-text("立即创建")'
                ).first
                try:
                    locator.wait_for(state="visible", timeout=5_000)
                    locator.click(timeout=5_000, force=True)
                    print(
                        f"[{account_id}] 新号落地页：Playwright 已点击立即创建 (第{attempt}次)",
                        flush=True,
                    )
                except Exception as click_exc:
                    print(
                        f"[{account_id}] 新号落地页：Playwright 点击失败，改用 JS 兜底 (第{attempt}次)："
                        f"{_safe_exc(click_exc)}",
                        flush=True,
                    )
                    result = page.run_js(f"return ({_FIND_CREATE_TARGET_JS})();")
                    if not isinstance(result, dict) or not result.get("clicked"):
                        print(
                            f"[{account_id}] 新号落地页：未找到立即创建按钮 (第{attempt}次)：{result}",
                            flush=True,
                        )
                        time.sleep(1)
                        continue
                    print(
                        f"[{account_id}] 新号落地页：JS 已点击立即创建 (第{attempt}次)：{result}",
                        flush=True,
                    )
            else:
                result = page.run_js(f"return ({_FIND_CREATE_TARGET_JS})();")
                if not isinstance(result, dict) or not result.get("clicked"):
                    print(
                        f"[{account_id}] 新号落地页：未找到立即创建按钮 (第{attempt}次)：{result}",
                        flush=True,
                    )
                    time.sleep(1)
                    continue

            time.sleep(2)
            if switch_to_latest_tab is not None:
                if switch_to_latest_tab(page):
                    print(f"[{account_id}] 新号落地页：已切换到最新标签页", flush=True)
            try:
                if raw_page is not None:
                    raw_page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
            return True
        except Exception as exc:
            print(
                f"[{account_id}] 新号落地页：点击立即创建异常 (第{attempt}次)：{_safe_exc(exc)}",
                flush=True,
            )
        time.sleep(1)

    return False

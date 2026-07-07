"""商品列表 Tab 导航：处理拼多多点击 Tab 时新开浏览器标签页的场景。"""

from __future__ import annotations

import time
from typing import Any, Callable

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.campaign.limited_time import (
    _live_context_pages,
    _switch_to_latest_tab,
)

GOODS_LIST_URLS = (
    "https://mms.pinduoduo.com/goods/goods_list",
    "https://mms.pinduoduo.com/goods/goods-list",
    "https://mms.pinduoduo.com/goods/list",
)

_GOODS_LIST_URL_PARTS = ("goods_list", "goods-list", "/goods/list")


def count_context_pages(page: DpPage) -> int:
    return len(_live_context_pages(page))


def _is_goods_list_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(part in lowered for part in _GOODS_LIST_URL_PARTS)


def _close_stale_goods_list_tab(page: DpPage, previous_raw_page: Any, account_id: str) -> None:
    """关闭切换 Tab 后遗留的旧商品列表标签页，避免越堆越多。"""
    try:
        if previous_raw_page is None or previous_raw_page.is_closed():
            return
        current = getattr(page, "_page", None)
        if previous_raw_page == current:
            return
        if not _is_goods_list_url(str(getattr(previous_raw_page, "url", "") or "")):
            return
        previous_raw_page.close()
        if account_id:
            print(f"[{account_id}] 已关闭多余的商品列表标签页", flush=True)
    except Exception:
        pass


def switch_to_latest_tab_if_opened(
    page: DpPage,
    tabs_before: int,
    *,
    account_id: str = "",
    tab_text: str = "",
) -> bool:
    """
    若点击 Tab 后浏览器新开标签页，切到最新页并关闭旧商品列表 Tab。
    返回是否发生了切换。
    """
    tabs_after = count_context_pages(page)
    if tabs_after <= tabs_before:
        return False

    previous_raw_page = getattr(page, "_page", None)
    if not _switch_to_latest_tab(page):
        return False

    _close_stale_goods_list_tab(page, previous_raw_page, account_id)
    if account_id and tab_text:
        print(
            f"[{account_id}] 点击「{tab_text}」后新开标签页，已切换到最新标签页继续操作",
            flush=True,
        )
    return True


def _verify_active_goods_list_tab(page: DpPage, tab_text: str) -> bool:
    """尽力确认当前页已处于目标 Tab（失败不阻断流程）。"""
    try:
        ok = page.run_js(
            """
            const tabText = String(arguments[0] || '').trim();
            if (!tabText) return true;
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            const nodes = Array.from(document.querySelectorAll('div, span, a, li, button'));
            for (const node of nodes) {
                const text = (node.innerText || node.textContent || '').trim();
                if (!text.startsWith(tabText)) continue;
                if (!isVisible(node)) continue;
                const cls = String(node.className || '');
                const aria = String(node.getAttribute?.('aria-selected') || '');
                const parentCls = String(node.parentElement?.className || '');
                if (
                    aria === 'true'
                    || /active|selected|current|checked/i.test(cls)
                    || /active|selected|current|checked/i.test(parentCls)
                ) {
                    return true;
                }
            }
            return null;
            """,
            tab_text,
        )
        return True if ok is None else bool(ok)
    except Exception:
        return True


def click_goods_list_tab(
    page: DpPage,
    tab_text: str,
    *,
    account_id: str = "",
) -> bool:
    """点击商品列表 Tab，并在新开标签页时自动切换绑定。"""
    tabs_before = count_context_pages(page)
    try:
        tab = page.ele(f"text:{tab_text}", timeout=3)
        if not tab:
            return False
        tab.click()
        time.sleep(1.5)
    except Exception:
        return False

    switch_to_latest_tab_if_opened(
        page,
        tabs_before,
        account_id=account_id,
        tab_text=tab_text,
    )
    return _verify_active_goods_list_tab(page, tab_text)


def refresh_goods_list_with_tab(
    page: DpPage,
    tab_text: str,
    *,
    account_id: str = "",
) -> None:
    """刷新当前商品列表页并切回指定 Tab（含新开标签页处理）。"""
    try:
        page._page.reload(wait_until="domcontentloaded")
    except Exception:
        return
    time.sleep(2)
    click_goods_list_tab(page, tab_text, account_id=account_id)


def open_goods_list_with_tab(
    page: DpPage,
    account_id: str,
    tab_text: str = "在售中",
    *,
    guard_overlays: Callable[..., Any] | None = None,
    ensure_modals_cleared: Callable[..., Any] | None = None,
) -> bool:
    """打开商品列表并切换到指定 Tab，自动处理新开标签页。"""
    for url in GOODS_LIST_URLS:
        try:
            page.get(url)
            time.sleep(3)
            if "login" in page.url:
                return False
            if page.ele("text:商品列表", timeout=2) or page.ele("text:商品ID", timeout=2):
                break
        except Exception:
            continue

    if guard_overlays is not None:
        guard_overlays(page, account_id, "", max_attempts=3)
    else:
        from pdd_agent.skills.pdd_blocking_overlay_guard import (
            ensure_pdd_blocking_overlays_cleared,
        )

        ensure_pdd_blocking_overlays_cleared(
            page,
            account_id,
            "",
            max_attempts=3,
        )

    if ensure_modals_cleared is not None:
        ensure_modals_cleared(page, account_id, "", max_attempts=3)
    else:
        from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
            ensure_post_publish_modals_cleared,
        )

        ensure_post_publish_modals_cleared(page, account_id, "", max_attempts=3)

    click_goods_list_tab(page, tab_text, account_id=account_id)
    return True

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
_TAB_KEY_BY_TEXT = {
    "全部": "key_0",
    "在售中": "key_1",
    "已下架": "key_2",
    "已售罄": "key_3",
    "发布中": "key_4",
    "已驳回": "key_6",
    "草稿箱": "key_7",
}


def count_context_pages(page: DpPage) -> int:
    return len(_live_context_pages(page))


def _is_goods_list_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(part in lowered for part in _GOODS_LIST_URL_PARTS)


def _log_tab_debug(account_id: str, message: str) -> None:
    if account_id:
        print(f"[{account_id}] [goods_tab] {message}", flush=True)


def _detect_active_tab_text(page: DpPage) -> str:
    """读取当前激活的商品列表 Tab 文本，便于日志排查。"""
    try:
        text = page.run_js(
            """
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
                if (!isVisible(node)) continue;
                const txt = (node.innerText || node.textContent || '').trim();
                if (!txt || txt.length > 20) continue;
                const cls = String(node.className || '');
                const aria = String(node.getAttribute?.('aria-selected') || '');
                const parentCls = String(node.parentElement?.className || '');
                if (
                    aria === 'true'
                    || /active|selected|current|checked/i.test(cls)
                    || /active|selected|current|checked/i.test(parentCls)
                ) {
                    if (/^(全部|在售中|已下架|已售罄|发布中|已驳回|草稿箱)/.test(txt)) return txt;
                }
            }
            return '';
            """,
        )
        return str(text or "").strip()
    except Exception:
        return ""


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
    若点击 Tab 后浏览器新开标签页，优先留在当前标签并关闭新开的商品列表页。
    返回是否处理了新开的标签页。
    """
    tabs_after = count_context_pages(page)
    if tabs_after <= tabs_before:
        return False
    _log_tab_debug(
        account_id,
        f"检测到点击「{tab_text or '-'}」后页签数变化：before={tabs_before}, after={tabs_after}",
    )

    current_raw_page = getattr(page, "_page", None)
    pages = _live_context_pages(page)
    closed_any = False
    for tab in reversed(pages):
        try:
            if tab is None or tab.is_closed():
                continue
            if current_raw_page is not None and tab == current_raw_page:
                continue
            if not _is_goods_list_url(str(getattr(tab, "url", "") or "")):
                continue
            tab.close()
            closed_any = True
            _log_tab_debug(account_id, "已关闭新开的商品列表标签页（保留当前标签）")
        except Exception:
            continue

    if not closed_any:
        previous_raw_page = current_raw_page
        if not _switch_to_latest_tab(page):
            return False
        _close_stale_goods_list_tab(page, previous_raw_page, account_id)
    elif current_raw_page is not None:
        try:
            if not current_raw_page.is_closed():
                page._page = current_raw_page
        except Exception:
            pass

    if account_id and tab_text and closed_any:
        print(
            f"[{account_id}] 点击「{tab_text}」触发新开标签页，已关闭新页并保留当前标签继续操作",
            flush=True,
        )
    elif account_id and tab_text:
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
        return bool(ok)
    except Exception:
        return False


def _force_click_goods_list_tab_current_page(page: DpPage, tab_text: str) -> bool:
    """在当前页面强制点击指定 Tab（去除 target=_blank），避免新开标签。"""
    try:
        clicked = page.run_js(
            """
            const tabText = String(arguments[0] || '').trim();
            if (!tabText) return false;
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            const nodes = Array.from(document.querySelectorAll('a, span, div, li, button'));
            const candidates = [];
            for (const node of nodes) {
                const text = (node.innerText || node.textContent || '').trim();
                if (!text.startsWith(tabText)) continue;
                if (!isVisible(node)) continue;
                const rect = node.getBoundingClientRect();
                // 顶部Tab通常在页面上半部分，避免误点左侧菜单「商品列表」
                if (rect.top > window.innerHeight * 0.65) continue;
                candidates.push(node);
            }
            if (!candidates.length) return false;
            const target = candidates[0];
            const anchor = target.closest('a');
            if (anchor) {
                try { anchor.setAttribute('target', '_self'); } catch (_) {}
                try { anchor.removeAttribute('target'); } catch (_) {}
            }
            try { target.click(); } catch (_) {}
            try { target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); } catch (_) {}
            return true;
            """,
            tab_text,
        )
        return bool(clicked)
    except Exception:
        return False


def _switch_goods_list_tab_by_url(page: DpPage, tab_text: str) -> bool:
    """通过 activeKeyNew 参数在当前页强制切换 Tab。"""
    key = _TAB_KEY_BY_TEXT.get(str(tab_text or "").strip())
    if not key:
        return False
    try:
        ok = page.run_js(
            """
            const key = String(arguments[0] || '').trim();
            if (!key) return false;
            const u = new URL(window.location.href);
            u.searchParams.set('activeKeyNew', key);
            window.location.href = u.toString();
            return true;
            """,
            key,
        )
        return bool(ok)
    except Exception:
        return False


def click_goods_list_tab(
    page: DpPage,
    tab_text: str,
    *,
    account_id: str = "",
) -> bool:
    """点击商品列表 Tab；优先在当前标签切换，必要时用 URL 参数强制切换。"""
    tabs_before = count_context_pages(page)
    _log_tab_debug(
        account_id,
        f"准备切换Tab到「{tab_text}」, current_url={str(getattr(page, 'url', '') or '')}",
    )
    _log_tab_debug(account_id, f"切换前激活Tab={_detect_active_tab_text(page) or 'unknown'}")
    if not _force_click_goods_list_tab_current_page(page, tab_text):
        _log_tab_debug(account_id, "当前页JS强制点击未命中，回退常规元素点击")
        try:
            tab = page.ele(f"text:{tab_text}", timeout=3)
            if not tab:
                _log_tab_debug(account_id, f"常规点击失败：未找到Tab元素「{tab_text}」")
                return False
            tab.click()
        except Exception:
            _log_tab_debug(account_id, f"常规点击异常：Tab「{tab_text}」")
            return False
    else:
        _log_tab_debug(account_id, f"当前页JS强制点击已触发：Tab「{tab_text}」")
    time.sleep(1.5)

    switched_or_closed = switch_to_latest_tab_if_opened(
        page,
        tabs_before,
        account_id=account_id,
        tab_text=tab_text,
    )
    tabs_after = count_context_pages(page)
    _log_tab_debug(
        account_id,
        f"点击后页签状态：processed_new_tab={switched_or_closed}, now_tabs={tabs_after}",
    )
    _log_tab_debug(account_id, f"点击后激活Tab={_detect_active_tab_text(page) or 'unknown'}")
    if _verify_active_goods_list_tab(page, tab_text):
        _log_tab_debug(account_id, f"Tab激活校验通过：{tab_text}")
        return True

    if account_id:
        print(
            f"[{account_id}] 点击「{tab_text}」后未激活目标Tab，改用 URL 参数强制切换",
            flush=True,
        )
    _log_tab_debug(account_id, f"准备URL强制切换：target_tab={tab_text}, key={_TAB_KEY_BY_TEXT.get(tab_text, '')}")
    if not _switch_goods_list_tab_by_url(page, tab_text):
        _log_tab_debug(account_id, f"URL强制切换失败：tab={tab_text}")
        return False
    time.sleep(2)
    verify_after_url = _verify_active_goods_list_tab(page, tab_text)
    _log_tab_debug(
        account_id,
        f"URL强制切换后校验：ok={verify_after_url}, active_tab={_detect_active_tab_text(page) or 'unknown'}",
    )
    return verify_after_url


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

"""推广平台：推广概况 → 商品推广 → 新建推广。"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.browser.sync_login import ensure_session_sync, is_login_url
from pdd_agent.core.config import AccountConfig
from pdd_agent.skills.campaign.limited_time import (
    _bind_page,
    _body_text,
    _click_text,
    _dismiss_message_popup,
    _ensure_page_binding,
    _live_context_pages,
    _safe_exc,
    _switch_to_latest_tab,
)

PROMOTION_OVERVIEW_URLS = (
    "https://mms.pinduoduo.com/mms/promotion/overview",
)
PRODUCT_PROMOTION_CREATE_URLS = (
    "https://yingxiao.pinduoduo.com/marketing/main/create/double",
    "https://mms.pinduoduo.com/mms/promotion/create",
)
PROMOTION_OVERVIEW_URL_PARTS = ("/mms/promotion/overview",)
PRODUCT_PROMOTION_CREATE_URL_PARTS = (
    "/marketing/main/create",
    "/create/double",
    "/mms/promotion/create",
    "/promotion/create",
)
PROMOTION_OVERVIEW_LINK = "https://mms.pinduoduo.com/mms/promotion/overview"

CREATE_PAGE_MARKERS = (
    "基础信息",
    "推广方案",
    "oCPX",
    "单元配置",
    "选择商品",
    "推广计划",
    "成交出价",
    "多多搜索",
    "多多场景",
    "智能创意",
    "流量配比",
    "完成",
)


def _ensure_session(
    page: DpPage,
    account: AccountConfig | None,
    account_id: str,
) -> dict[str, object]:
    result = ensure_session_sync(page, account)
    if not result.get("logged_in") and account is not None:
        result = ensure_session_sync(page, account)
    if not result.get("logged_in"):
        print(f"[{account_id}] 推广任务登录失败: {result}", flush=True)
    return result


def _page_url(page: DpPage) -> str:
    try:
        return str(page.url or "")
    except Exception:
        return ""


def _is_page_not_found(page: DpPage) -> bool:
    text = _body_text(page)
    return "页面不存在" in text or "返回概况页" in text


def _is_promotion_overview_page(page: DpPage) -> bool:
    """推广概况页：商品推广 Tab + 新建推广入口。"""
    if _is_page_not_found(page):
        return False
    url = _page_url(page)
    text = _body_text(page)
    if not text:
        return False
    has_promotion_context = (
        "/mms/promotion/overview" in url
        or "yingxiao.pinduoduo.com" in url
        or "推广概况" in text
        or "商品推广" in text
        or "实时概况" in text
    )
    if not has_promotion_context:
        return False
    has_product_tab = "商品推广" in text
    has_create_entry = "新建推广" in text or "+ 新建推广" in text.replace(" ", "")
    has_overview_stats = any(
        marker in text for marker in ("推广中", "余额不足", "实时概况", "账户余额")
    )
    return has_product_tab and (has_create_entry or has_overview_stats)


def _is_product_promotion_create_page(page: DpPage) -> bool:
    """新建推广后的计划创建页（含 SPA 路由 / 新标签页）。"""
    url = _page_url(page)
    text = _body_text(page)
    if any(part in url for part in PRODUCT_PROMOTION_CREATE_URL_PARTS):
        return True
    marker_count = sum(1 for marker in CREATE_PAGE_MARKERS if marker in text)
    if marker_count >= 2:
        return True
    try:
        js_state = page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 8 && r.height > 8
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            const text = (document.body?.innerText || '').replace(/\\s+/g, ' ');
            const markers = ['基础信息', '推广方案', 'oCPX', '单元配置', '选择商品', '推广计划'];
            const hit = markers.filter((m) => text.includes(m)).length;
            const wizard = document.querySelector(
                '[class*="Create"], [class*="create"], [class*="PlanCreate"], form, [role="dialog"]'
            );
            return {
                marker_count: hit,
                has_wizard: !!(wizard && isVisible(wizard)),
                url: location.href,
            };
            """
        ) or {}
    except Exception:
        js_state = {}
    if int(js_state.get("marker_count") or 0) >= 2:
        return True
    if js_state.get("has_wizard") and int(js_state.get("marker_count") or 0) >= 1:
        return True
    return False


def _bind_best_create_page(page: DpPage, before_urls: set[str]) -> dict[str, Any]:
    """点击新建推广后，在当前页或新标签页中绑定到创建页。"""
    pages = _live_context_pages(page)
    candidates: list[tuple[int, Any, str]] = []

    for raw in pages:
        try:
            url = str(getattr(raw, "url", "") or "")
        except Exception:
            continue
        if url in before_urls and "/mms/promotion/overview" in url:
            pass
        _bind_page(page, raw)
        score = 0
        if any(part in url for part in PRODUCT_PROMOTION_CREATE_URL_PARTS):
            score += 100
        if url not in before_urls:
            score += 40
        if _is_product_promotion_create_page(page):
            score += 80
        candidates.append((score, raw, url))

    if not candidates:
        return {"bound": False, "reason": "no_live_pages"}

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_page, best_url = candidates[0]
    _bind_page(page, best_page)
    try:
        best_page.bring_to_front()
    except Exception:
        pass
    return {"bound": best_score > 0, "score": best_score, "url": best_url}


def _wait_promotion_overview_page(page: DpPage, timeout: int = 15) -> bool:
    for _ in range(timeout):
        if _is_promotion_overview_page(page):
            return True
        time.sleep(1)
    return False


def _wait_product_promotion_create_page(
    page: DpPage,
    *,
    before_urls: set[str] | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    before_urls = before_urls or set()
    for _ in range(timeout):
        bind_result = _bind_best_create_page(page, before_urls)
        if _is_product_promotion_create_page(page):
            return {"ready": True, "url": _page_url(page), "bind": bind_result}
        time.sleep(1)
    return {"ready": False, "url": _page_url(page)}


def _click_sidebar_promotion_overview(page: DpPage) -> dict[str, Any]:
    """商家后台左侧「流量运营 → 推广概况」。"""
    return page.run_js(
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

        function norm(text) {
            return (text || '').replace(/\\s+/g, '').trim();
        }

        function clickEl(el) {
            const target = el.closest('a,button,[role="menuitem"],li') || el;
            target.scrollIntoView({ block: 'center', inline: 'nearest' });
            target.click();
            return true;
        }

        function findSidebarItem(label) {
            const nodes = Array.from(document.querySelectorAll('a,span,div,li,p'));
            const hits = [];
            for (const el of nodes) {
                if (!isVisible(el)) continue;
                const text = norm(el.innerText || el.textContent || '');
                if (text !== label && !text.endsWith(label)) continue;
                const rect = el.getBoundingClientRect();
                if (rect.left > window.innerWidth * 0.35) continue;
                hits.push({ el, rect, text, left: rect.left, top: rect.top });
            }
            hits.sort((a, b) => a.left - b.left || a.top - b.top);
            return hits[0]?.el || null;
        }

        const directLink = Array.from(document.querySelectorAll('a[href]'))
            .find((el) => {
                const href = String(el.getAttribute('href') || '');
                return href.includes('/mms/promotion/overview');
            });
        if (directLink && isVisible(directLink)) {
            clickEl(directLink);
            return {
                clicked: true,
                method: 'sidebar_href',
                href: directLink.getAttribute('href') || '',
            };
        }

        for (const groupLabel of ['流量运营', '推广平台', '推广']) {
            const group = findSidebarItem(groupLabel);
            if (group) {
                clickEl(group);
            }
        }

        const overviewLink = Array.from(document.querySelectorAll('a[href*="/mms/promotion/overview"]'))
            .find(isVisible);
        if (overviewLink) {
            clickEl(overviewLink);
            return {
                clicked: true,
                method: 'sidebar_overview_href',
                href: overviewLink.getAttribute('href') || '',
            };
        }

        const overview = findSidebarItem('推广概况');
        if (!overview) {
            return { clicked: false, reason: 'sidebar_promotion_overview_not_found' };
        }
        clickEl(overview);
        return { clicked: true, method: 'sidebar_promotion_overview' };
        """
    ) or {"clicked": False, "reason": "sidebar_click_js_failed"}


def _open_promotion_overview(
    page: DpPage,
    account_id: str,
    account: AccountConfig | None = None,
) -> bool:
    """从商家后台侧边栏进入推广概况页。"""
    _ensure_session(page, account, account_id)
    _dismiss_message_popup(page)

    print(f"[{account_id}] 从商家后台侧边栏进入推广概况", flush=True)
    try:
        page.get("https://mms.pinduoduo.com/home/")
        time.sleep(2)
        if is_login_url(_page_url(page)):
            relogin = _ensure_session(page, account, account_id)
            if not relogin.get("logged_in"):
                return False
        _dismiss_message_popup(page)
        click_result = _click_sidebar_promotion_overview(page)
        if not click_result.get("clicked"):
            if not _click_text(page, "流量运营", timeout=3):
                _click_text(page, "推广平台", timeout=2)
            time.sleep(1)
            if not _click_text(page, "推广概况", timeout=5):
                print(f"[{account_id}] 侧边栏未找到推广概况，尝试直达链接", flush=True)
                page.get(PROMOTION_OVERVIEW_LINK)
                time.sleep(3)
        else:
            time.sleep(3)
        _switch_to_latest_tab(page)
        _ensure_page_binding(page, preferred_url_parts=PROMOTION_OVERVIEW_URL_PARTS, timeout=5)
        if _wait_promotion_overview_page(page, timeout=12):
            print(f"[{account_id}] 已通过侧边栏进入推广概况", flush=True)
            return True
    except Exception as exc:
        print(f"[{account_id}] 菜单进入推广概况异常：{_safe_exc(exc)}", flush=True)

    for url in PROMOTION_OVERVIEW_URLS:
        try:
            page.get(url)
            time.sleep(3)
            if is_login_url(_page_url(page)):
                relogin = _ensure_session(page, account, account_id)
                if not relogin.get("logged_in"):
                    return False
                page.get(url)
                time.sleep(3)
            if _is_page_not_found(page):
                print(f"[{account_id}] 推广概况 URL 返回页面不存在: {url}", flush=True)
                continue
            _switch_to_latest_tab(page)
            _ensure_page_binding(page, preferred_url_parts=PROMOTION_OVERVIEW_URL_PARTS, timeout=3)
            if _wait_promotion_overview_page(page, timeout=8):
                print(f"[{account_id}] 已通过 mms 链接进入推广概况", flush=True)
                return True
        except Exception as exc:
            print(f"[{account_id}] 打开推广概况 URL 异常：{_safe_exc(exc)}", flush=True)

    return False


def _ensure_product_promotion_tab(page: DpPage) -> dict[str, Any]:
    """确保当前在「商品推广」Tab。"""
    text = _body_text(page)
    if "商品推广" not in text:
        return {"switched": False, "reason": "product_promotion_tab_not_found", "skipped": True}

    result = page.run_js(
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

        function norm(text) {
            return (text || '').replace(/\\s+/g, '').trim();
        }

        const tabs = Array.from(document.querySelectorAll('a,button,div,span,li'))
            .filter(isVisible)
            .filter((el) => norm(el.innerText || el.textContent || '') === '商品推广');
        if (!tabs.length) {
            return { switched: false, reason: 'product_promotion_tab_not_found' };
        }
        tabs.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
        const tab = tabs[0];
        tab.click();
        return { switched: true, method: 'click_product_promotion_tab' };
        """
    ) or {"switched": False, "reason": "product_promotion_tab_js_failed"}

    if result.get("switched"):
        time.sleep(2)
    return result


def _click_new_promotion(page: DpPage, account_id: str) -> dict[str, Any]:
    """商品推广 Tab 内点击「新建推广」按钮（CreatePromotionBtn）。"""
    _ensure_product_promotion_tab(page)

    result = page.run_js(
        """
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 8 && r.height > 8
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }

        function norm(text) {
            return (text || '').replace(/\\s+/g, '').trim();
        }

        function buttonLabel(btn) {
            return norm(btn.innerText || btn.textContent || '');
        }

        function clickBtn(btn) {
            btn.scrollIntoView({ block: 'center', inline: 'nearest' });
            btn.click();
            return true;
        }

        const selectors = [
            'button[class*="CreatePromotionBtn"]',
            'div[class*="GeneralV1_left"] button.anq-btn-primary',
            'button.anq-btn-primary',
        ];

        for (const selector of selectors) {
            const buttons = Array.from(document.querySelectorAll(selector)).filter(isVisible);
            for (const btn of buttons) {
                const label = buttonLabel(btn);
                if (label !== '新建推广') continue;
                clickBtn(btn);
                return {
                    clicked: true,
                    text: label,
                    method: 'selector_' + selector,
                    className: btn.className || '',
                };
            }
        }

        const spans = Array.from(document.querySelectorAll('button span, a span'))
            .filter(isVisible)
            .filter((el) => norm(el.innerText || el.textContent || '') === '新建推广');
        for (const span of spans) {
            const btn = span.closest('button,a,[role="button"]');
            if (!btn || !isVisible(btn)) continue;
            const label = buttonLabel(btn);
            if (label.includes('查看全部')) continue;
            clickBtn(btn);
            return {
                clicked: true,
                text: label,
                method: 'span_closest_button',
                className: btn.className || '',
            };
        }

        return { clicked: false, reason: 'new_promotion_button_not_found' };
        """
    ) or {"clicked": False, "reason": "new_promotion_js_failed"}

    if result.get("clicked"):
        time.sleep(3)
        return result

    if _click_text(page, "新建推广", timeout=3):
        time.sleep(3)
        return {"clicked": True, "text": "新建推广", "method": "text_click"}

    print(f"[{account_id}] 未找到新建推广按钮，尝试直达创建页 URL", flush=True)
    for url in PRODUCT_PROMOTION_CREATE_URLS:
        try:
            page.get(url)
            time.sleep(3)
            wait_result = _wait_product_promotion_create_page(page, timeout=8)
            if wait_result.get("ready"):
                return {"clicked": True, "method": "direct_create_url", "url": url}
        except Exception:
            continue

    return {"clicked": False, "reason": "new_promotion_button_not_found"}


def open_product_promotion_create(
    page: DpPage,
    account_id: str,
    *,
    pdd_product_ids: list[str] | None = None,
    account: AccountConfig | None = None,
) -> dict[str, Any]:
    """打开推广概况并点击新建推广（到创建页为止）。"""
    selected_pdd_product_ids = list(dict.fromkeys(pdd_product_ids or []))
    try:
        if not _open_promotion_overview(page, account_id, account=account):
            return {
                "status": "failed",
                "step": "open_promotion_overview",
                "error": "未能进入推广概况页或会话已跳转登录",
                "current_url": _page_url(page),
                "selected_pdd_product_ids": selected_pdd_product_ids,
            }

        click_result = _click_new_promotion(page, account_id)
        if not click_result.get("clicked"):
            return {
                "status": "failed",
                "step": "click_new_promotion",
                "error": click_result.get("reason") or "未找到或无法点击新建推广",
                "click_result": click_result,
                "current_url": _page_url(page),
                "selected_pdd_product_ids": selected_pdd_product_ids,
            }

        before_urls = {str(getattr(p, "url", "") or "") for p in _live_context_pages(page)}
        wait_result = _wait_product_promotion_create_page(page, before_urls=before_urls, timeout=15)
        if not wait_result.get("ready"):
            body_preview = _body_text(page)[:300]
            return {
                "status": "failed",
                "step": "wait_create_page",
                "error": "已点击新建推广，但未进入计划创建页",
                "click_result": click_result,
                "wait_result": wait_result,
                "current_url": _page_url(page),
                "body_preview": body_preview,
                "selected_pdd_product_ids": selected_pdd_product_ids,
            }

        print(f"[{account_id}] 已进入商品推广新建页", flush=True)
        return {
            "status": "success",
            "step": "create_page_ready",
            "message": "已进入推广概况并打开新建推广页",
            "click_result": click_result,
            "wait_result": wait_result,
            "current_url": _page_url(page),
            "selected_pdd_product_ids": selected_pdd_product_ids,
            "open_tabs": len(_live_context_pages(page)),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "step": "open_product_promotion_create",
            "error": _safe_exc(exc),
            "current_url": _page_url(page),
            "selected_pdd_product_ids": selected_pdd_product_ids,
        }

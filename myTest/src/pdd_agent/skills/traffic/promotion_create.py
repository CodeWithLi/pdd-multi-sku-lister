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
PRODUCT_PROMOTION_CREATE_URLS: tuple[str, ...] = ()
PROMOTION_OVERVIEW_URL_PARTS = ("/mms/promotion/overview", "promotionOverview")
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
    "添加推广商品",
)
ADD_PRODUCT_DRAWER_MARKERS = ("添加推广商品", "可推广商品")
PRODUCT_SEARCH_BATCH_SIZE = 30
UNWANTED_TAB_URL_PARTS = (
    "/home/",
    "/home",
    "/goods/goods_list",
    "/goods/list",
    "/login",
    "/marketing/main/create",
)
PROMOTION_TAB_URL_PARTS = (
    "yingxiao.pinduoduo.com",
    "/mms/promotion/",
    "promotionOverview",
    "promotion/overview",
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
    """新建推广后的计划创建页（含 SPA 路由 / 新标签页 / 添加商品抽屉）。"""
    if _is_add_promotion_product_drawer(page):
        return True
    url = _page_url(page)
    text = _body_text(page)
    if any(part in url for part in PRODUCT_PROMOTION_CREATE_URL_PARTS):
        return True
    if "promotionOverview" in url and "添加推广商品" in text:
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


def _is_unwanted_tab_url(url: str) -> bool:
    value = str(url or "").strip().lower()
    if not value or value in {"about:blank"}:
        return True
    if any(part in value for part in UNWANTED_TAB_URL_PARTS):
        if "promotion" not in value:
            return True
    return False


def _is_promotion_tab_url(url: str) -> bool:
    value = str(url or "")
    return any(part in value for part in PROMOTION_TAB_URL_PARTS)


def _is_promotion_workflow_ready(page: DpPage) -> bool:
    """点击新建推广后：抽屉已打开。"""
    if _is_page_not_found(page):
        return False
    return _is_add_promotion_product_drawer(page)


def _read_add_product_drawer_state(page: DpPage) -> dict[str, Any]:
    """通过 DOM 检测「添加推广商品」抽屉是否可见。"""
    try:
        return page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 40 && r.height > 40
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }

            function norm(text) {
                return (text || '').replace(/\\s+/g, '').trim();
            }

            const roots = Array.from(document.querySelectorAll(
                '.anq-drawer-content-wrapper, .anq-drawer-content, [class*="GoodsSelection"], [class*="anq-drawer"]'
            )).filter(isVisible);

            for (const root of roots) {
                const text = (root.innerText || root.textContent || '');
                if (!text.includes('添加推广商品')) continue;
                const hasQuery = text.includes('查询');
                const hasInput = !!root.querySelector('input');
                const title = Array.from(root.querySelectorAll('*'))
                    .filter(isVisible)
                    .map((el) => norm(el.innerText || el.textContent || ''))
                    .find((value) => value === '添加推广商品' || value.includes('添加推广商品'));
                return {
                    visible: true,
                    has_query: hasQuery,
                    has_input: hasInput,
                    title: title || '添加推广商品',
                    text_preview: text.replace(/\\s+/g, ' ').trim().slice(0, 180),
                };
            }

            const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ');
            if (
                bodyText.includes('添加推广商品')
                && bodyText.includes('查询')
                && (bodyText.includes('可推广商品') || bodyText.includes('商品ID') || bodyText.includes('商品:'))
            ) {
                return {
                    visible: true,
                    has_query: true,
                    has_input: !!document.querySelector('input'),
                    title: '添加推广商品',
                    text_preview: bodyText.slice(0, 180),
                    source: 'body_text',
                };
            }

            return { visible: false, reason: 'drawer_not_visible' };
            """
        ) or {"visible": False, "reason": "drawer_state_js_failed"}
    except Exception as exc:
        return {"visible": False, "reason": _safe_exc(exc)}


def _is_add_promotion_product_drawer(page: DpPage) -> bool:
    """「添加推广商品」抽屉是否已打开。"""
    return bool(_read_add_product_drawer_state(page).get("visible"))


def _score_promotion_page(page: DpPage, raw_page: Any) -> int:
    try:
        _bind_page(page, raw_page)
    except Exception:
        return -1
    url = _page_url(page)
    if _is_unwanted_tab_url(url):
        return -1000
    text = _body_text(page)
    score = 0
    if _is_add_promotion_product_drawer(page):
        score += 300
    if "yingxiao.pinduoduo.com" in url:
        score += 120
    if "promotionOverview" in url:
        score += 100
    if "/mms/promotion/" in url:
        score += 80
    if _is_promotion_tab_url(url):
        score += 60
    if "商品推广" in text:
        score += 40
    if "新建推广" in text:
        score += 20
    if "添加推广商品" in text:
        score += 150
    if _is_product_promotion_create_page(page):
        score += 50
    return score


def _find_best_promotion_page(page: DpPage) -> Any | None:
    pages = _live_context_pages(page)
    if not pages:
        return getattr(page, "_page", None)
    scored = [(score, raw) for raw in pages if (score := _score_promotion_page(page, raw)) > 0]
    if not scored:
        promotion_pages = [raw for raw in pages if _is_promotion_tab_url(str(getattr(raw, "url", "") or ""))]
        if promotion_pages:
            return promotion_pages[-1]
        return pages[-1] if pages else None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _close_unwanted_tabs(page: DpPage, account_id: str) -> dict[str, Any]:
    """无条件关闭首页、404 创建页等无关标签页。"""
    closed_urls: list[str] = []
    for item in list(_live_context_pages(page)):
        try:
            if item.is_closed():
                continue
            url = str(item.url or "")
            should_close = _is_unwanted_tab_url(url)
            if not should_close:
                _bind_page(page, item)
                if _is_page_not_found(page):
                    should_close = True
            if not should_close:
                continue
            item.close()
            closed_urls.append(url)
            print(f"[{account_id}] 已关闭无关标签页: {url}", flush=True)
        except Exception:
            continue
    return {"closed": closed_urls, "closed_count": len(closed_urls)}


def _focus_best_promotion_page(page: DpPage, account_id: str) -> dict[str, Any]:
    """关闭无关页并切到最佳推广标签。"""
    unwanted = _close_unwanted_tabs(page, account_id)
    best_page = _find_best_promotion_page(page)
    if best_page is None:
        return {"focused": False, "reason": "no_best_page", "unwanted": unwanted}

    _bind_page(page, best_page)
    try:
        best_page.bring_to_front()
    except Exception:
        pass
    time.sleep(0.5)
    return {
        "focused": True,
        "url": _page_url(page),
        "unwanted": unwanted,
    }


def _close_other_promotion_tabs(page: DpPage, account_id: str) -> dict[str, Any]:
    """保留最佳推广页，关闭其余标签页。"""
    _close_unwanted_tabs(page, account_id)
    best_page = _find_best_promotion_page(page)
    if best_page is None:
        return {"closed": [], "reason": "no_best_page"}

    closed_urls: list[str] = []
    for item in list(_live_context_pages(page)):
        if item is best_page:
            continue
        try:
            if item.is_closed():
                continue
            url = str(item.url or "")
            item.close()
            closed_urls.append(url)
            print(f"[{account_id}] 已关闭多余标签页: {url}", flush=True)
        except Exception:
            continue

    _bind_page(page, best_page)
    try:
        best_page.bring_to_front()
    except Exception:
        pass
    time.sleep(1)
    return {
        "closed": closed_urls,
        "kept_url": str(getattr(best_page, "url", "") or ""),
        "closed_count": len(closed_urls),
    }


def _wait_add_promotion_product_drawer(
    page: DpPage,
    *,
    account_id: str = "",
    timeout: int = 20,
) -> dict[str, Any]:
    last_state: dict[str, Any] = {}
    for _ in range(timeout):
        if account_id:
            _close_unwanted_tabs(page, account_id)
            _focus_best_promotion_page(page, account_id)
        last_state = _read_add_product_drawer_state(page)
        if last_state.get("visible"):
            return {"ready": True, "url": _page_url(page), "drawer": last_state}
        time.sleep(1)
    return {"ready": False, "url": _page_url(page), "drawer": last_state}


def _fill_promotion_product_ids(page: DpPage, product_ids: list[str]) -> dict[str, Any]:
    """在「添加推广商品」抽屉的商品输入框填入 ID（空格分隔）。"""
    query = " ".join(product_ids)
    if not query:
        return {"filled": False, "reason": "empty_product_ids"}

    result = page.run_js(
        """
        (query) => {
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

            function drawerRoot() {
                const drawers = Array.from(document.querySelectorAll(
                    '.anq-drawer-content-wrapper, [class*="GoodsSelection"], [class*="anq-drawer"]'
                )).filter(isVisible);
                for (const root of drawers) {
                    const text = (root.innerText || root.textContent || '');
                    if (text.includes('添加推广商品')) return root;
                }
                const bodyText = document.body?.innerText || '';
                if (bodyText.includes('添加推广商品')) return document.body;
                return null;
            }

            function setInputValue(input, value) {
                input.focus();
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                )?.set;
                if (setter) setter.call(input, value);
                else input.value = value;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }

            const root = drawerRoot();
            if (!root) return { filled: false, reason: 'add_product_drawer_not_found' };

            const inputs = Array.from(root.querySelectorAll('input'))
                .filter(isVisible)
                .filter((el) => {
                    const placeholder = el.getAttribute('placeholder') || '';
                    return placeholder.includes('商品')
                        || placeholder.includes('ID')
                        || placeholder.includes('id');
                });
            if (!inputs.length) {
                return { filled: false, reason: 'product_id_input_not_found' };
            }

            const input = inputs[0];
            setInputValue(input, query);
            return {
                filled: true,
                value: input.value,
                placeholder: input.getAttribute('placeholder') || '',
                method: 'js_drawer_input',
            };
        }
        """,
        query,
    ) or {"filled": False, "reason": "fill_product_ids_js_failed"}

    if result.get("filled"):
        return {**result, "query": query}

    try:
        raw_page = getattr(page, "_page")
        drawer = raw_page.locator(
            '.anq-drawer-content-wrapper:has-text("添加推广商品"), '
            '[class*="GoodsSelection"]:has-text("添加推广商品")'
        ).last
        input_locator = drawer.locator(
            'input[placeholder*="商品"], input[placeholder*="ID"]'
        ).first
        input_locator.wait_for(state="visible", timeout=5_000)
        input_locator.click(timeout=3_000)
        input_locator.fill(query, timeout=5_000)
        actual = str(input_locator.input_value(timeout=2_000) or "").strip()
        if actual:
            return {
                "filled": True,
                "value": actual,
                "query": query,
                "method": "playwright_drawer_input",
            }
    except Exception as exc:
        return {"filled": False, "reason": _safe_exc(exc), "query": query}

    return {**result, "query": query}


def _click_promotion_product_query(page: DpPage, account_id: str) -> dict[str, Any]:
    """点击「添加推广商品」抽屉内的「查询」按钮。"""
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

        function drawerRoot() {
            const drawers = Array.from(document.querySelectorAll(
                '.anq-drawer-content-wrapper, [class*="GoodsSelection"], [class*="anq-drawer"]'
            )).filter(isVisible);
            for (const root of drawers) {
                const text = (root.innerText || root.textContent || '');
                if (text.includes('添加推广商品')) return root;
            }
            if ((document.body?.innerText || '').includes('添加推广商品')) {
                return document.body;
            }
            return null;
        }

        const root = drawerRoot();
        if (!root) return { clicked: false, reason: 'add_product_drawer_not_found' };

        const testBtn = root.querySelector('button[data-testid="QueryPanel_confirm"]');
        if (testBtn && isVisible(testBtn)) {
            testBtn.click();
            return { clicked: true, method: 'QueryPanel_confirm', text: '查询' };
        }

        const buttons = Array.from(root.querySelectorAll('button.anq-btn-primary, button'))
            .filter(isVisible)
            .filter((btn) => norm(btn.innerText || btn.textContent || '') === '查询');
        if (buttons.length) {
            buttons[0].click();
            return { clicked: true, method: 'drawer_query_button', text: '查询' };
        }

        return { clicked: false, reason: 'query_button_not_found' };
        """
    ) or {"clicked": False, "reason": "click_query_js_failed"}

    if result.get("clicked"):
        time.sleep(2)
        return result

    try:
        raw_page = getattr(page, "_page")
        drawer = raw_page.locator(
            '.anq-drawer-content-wrapper:has-text("添加推广商品"), '
            '[class*="GoodsSelection"]:has-text("添加推广商品")'
        ).last
        query_btn = drawer.locator('button[data-testid="QueryPanel_confirm"]').first
        if not query_btn.count():
            query_btn = drawer.locator('button.anq-btn-primary:has-text("查询")').first
        query_btn.wait_for(state="visible", timeout=5_000)
        query_btn.click(timeout=5_000)
        time.sleep(2)
        return {"clicked": True, "method": "playwright_query_button", "text": "查询"}
    except Exception as exc:
        print(f"[{account_id}] 推广商品查询按钮点击失败: {_safe_exc(exc)}", flush=True)

    if _click_text(page, "查询", timeout=3):
        time.sleep(2)
        return {"clicked": True, "method": "text_click", "text": "查询"}

    return {**result}


def _search_promotion_products(
    page: DpPage,
    account_id: str,
    product_ids: list[str],
) -> dict[str, Any]:
    """在添加推广商品抽屉中输入 ID 并查询。"""
    ids = [str(item).strip() for item in product_ids if str(item).strip()]
    if not ids:
        return {"status": "failed", "step": "search_promotion_products", "error": "无有效商品 ID"}

    if not _is_add_promotion_product_drawer(page):
        drawer_wait = _wait_add_promotion_product_drawer(
            page,
            account_id=account_id,
            timeout=12,
        )
        if not drawer_wait.get("ready"):
            return {
                "status": "failed",
                "step": "wait_add_product_drawer",
                "error": "未找到添加推广商品抽屉",
                "drawer_wait": drawer_wait,
            }
    else:
        drawer_wait = {"ready": True, "skipped": True, "drawer": _read_add_product_drawer_state(page)}

    batches = [
        ids[index : index + PRODUCT_SEARCH_BATCH_SIZE]
        for index in range(0, len(ids), PRODUCT_SEARCH_BATCH_SIZE)
    ]
    batch_results: list[dict[str, Any]] = []
    for batch_index, batch in enumerate(batches):
        fill_result = _fill_promotion_product_ids(page, batch)
        if not fill_result.get("filled"):
            return {
                "status": "failed",
                "step": "fill_promotion_product_ids",
                "error": fill_result.get("reason") or "填写商品 ID 失败",
                "batch_index": batch_index,
                "fill_result": fill_result,
                "batch_results": batch_results,
            }
        query_result = _click_promotion_product_query(page, account_id)
        if not query_result.get("clicked"):
            return {
                "status": "failed",
                "step": "click_promotion_product_query",
                "error": query_result.get("reason") or "点击查询失败",
                "batch_index": batch_index,
                "fill_result": fill_result,
                "query_result": query_result,
                "batch_results": batch_results,
            }
        batch_results.append(
            {
                "batch_index": batch_index,
                "product_ids": batch,
                "fill_result": fill_result,
                "query_result": query_result,
            }
        )
        if batch_index + 1 < len(batches):
            time.sleep(2)

    print(f"[{account_id}] 已在添加推广商品抽屉查询 {len(ids)} 个商品 ID", flush=True)
    return {
        "status": "success",
        "step": "product_ids_searched",
        "searched_count": len(ids),
        "batch_count": len(batches),
        "batch_results": batch_results,
    }


def _bind_best_create_page(page: DpPage, before_urls: set[str]) -> dict[str, Any]:
    """点击新建推广后，绑定到推广页/创建页，绝不落到首页。"""
    _close_unwanted_tabs(page, "")
    pages = _live_context_pages(page)
    candidates: list[tuple[int, Any, str]] = []

    for raw in pages:
        try:
            url = str(getattr(raw, "url", "") or "")
        except Exception:
            continue
        if _is_unwanted_tab_url(url):
            continue
        score = _score_promotion_page(page, raw)
        if score <= 0:
            continue
        if url not in before_urls:
            score += 30
        if _is_promotion_workflow_ready(page):
            score += 120
        candidates.append((score, raw, url))

    if not candidates:
        return {"bound": False, "reason": "no_promotion_page_candidate"}

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_page, best_url = candidates[0]
    _bind_page(page, best_page)
    try:
        best_page.bring_to_front()
    except Exception:
        pass
    return {"bound": True, "score": best_score, "url": best_url}


def _wait_promotion_overview_page(page: DpPage, timeout: int = 15) -> bool:
    for _ in range(timeout):
        if _is_promotion_overview_page(page):
            return True
        time.sleep(1)
    return False


def _wait_product_promotion_create_page(
    page: DpPage,
    *,
    account_id: str = "",
    before_urls: set[str] | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    before_urls = before_urls or set()
    last_bind: dict[str, Any] = {}
    for _ in range(timeout):
        if account_id:
            _close_unwanted_tabs(page, account_id)
        last_bind = _bind_best_create_page(page, before_urls)
        if _is_promotion_workflow_ready(page):
            return {"ready": True, "url": _page_url(page), "bind": last_bind}
        time.sleep(1)
    return {"ready": False, "url": _page_url(page), "bind": last_bind}


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
        _focus_best_promotion_page(page, account_id)
        _ensure_page_binding(page, preferred_url_parts=PROMOTION_OVERVIEW_URL_PARTS, timeout=5)
        if _wait_promotion_overview_page(page, timeout=12):
            _close_other_promotion_tabs(page, account_id)
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
            _focus_best_promotion_page(page, account_id)
            _ensure_page_binding(page, preferred_url_parts=PROMOTION_OVERVIEW_URL_PARTS, timeout=3)
            if _wait_promotion_overview_page(page, timeout=8):
                _close_other_promotion_tabs(page, account_id)
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

        function isNewPromotionLabel(text) {
            const value = norm(text);
            return value === '新建推广'
                || value === '+新建推广'
                || value.endsWith('新建推广');
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
                if (!isNewPromotionLabel(label)) continue;
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
            .filter((el) => isNewPromotionLabel(norm(el.innerText || el.textContent || '')));
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
        time.sleep(2)
        return result

    try:
        raw_page = getattr(page, "_page")
        btn = raw_page.locator('button[class*="CreatePromotionBtn"]').filter(has_text="新建推广").first
        if btn.count():
            btn.click(timeout=5_000)
            time.sleep(2)
            return {"clicked": True, "text": "+ 新建推广", "method": "playwright_create_btn"}
    except Exception as exc:
        print(f"[{account_id}] Playwright 点击新建推广失败: {_safe_exc(exc)}", flush=True)

    for label in ("+ 新建推广", "新建推广"):
        if _click_text(page, label, timeout=3):
            time.sleep(2)
            return {"clicked": True, "text": label, "method": "text_click"}

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

        _focus_best_promotion_page(page, account_id)
        _close_other_promotion_tabs(page, account_id)

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

        _close_unwanted_tabs(page, account_id)
        drawer_wait = _wait_add_promotion_product_drawer(
            page,
            account_id=account_id,
            timeout=25,
        )
        if not drawer_wait.get("ready"):
            body_preview = _body_text(page)[:300]
            open_tabs = [str(getattr(p, "url", "") or "") for p in _live_context_pages(page)]
            balance_hint = ""
            if "余额不足" in body_preview or "推广已中断" in body_preview:
                balance_hint = "；推广账户余额不足，可能无法打开添加商品抽屉，请先充值"
            return {
                "status": "failed",
                "step": "wait_add_product_drawer",
                "error": f"未找到添加推广商品抽屉{balance_hint}",
                "click_result": click_result,
                "drawer_wait": drawer_wait,
                "current_url": _page_url(page),
                "open_tabs": open_tabs,
                "body_preview": body_preview,
                "selected_pdd_product_ids": selected_pdd_product_ids,
            }

        print(f"[{account_id}] 已打开添加推广商品抽屉", flush=True)

        close_result = _close_other_promotion_tabs(page, account_id)
        search_result = _search_promotion_products(page, account_id, selected_pdd_product_ids)
        if search_result.get("status") != "success":
            return {
                "status": "failed",
                "step": search_result.get("step") or "search_promotion_products",
                "error": search_result.get("error") or "推广商品查询失败",
                "click_result": click_result,
                "drawer_wait": drawer_wait,
                "close_result": close_result,
                "search_result": search_result,
                "current_url": _page_url(page),
                "selected_pdd_product_ids": selected_pdd_product_ids,
            }

        return {
            "status": "success",
            "step": "product_ids_searched",
            "message": f"已打开新建推广并查询 {len(selected_pdd_product_ids)} 个商品 ID",
            "click_result": click_result,
            "drawer_wait": drawer_wait,
            "close_result": close_result,
            "search_result": search_result,
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

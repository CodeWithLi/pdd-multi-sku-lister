"""推广平台：推广概况 → 商品推广 → 新建推广。"""

from __future__ import annotations

import json
import re
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
    "https://yingxiao.pinduoduo.com/mains/promotionOverview",
)
PRODUCT_PROMOTION_CREATE_URLS: tuple[str, ...] = ()
PROMOTION_OVERVIEW_URL_PARTS = ("promotionOverview", "yingxiao.pinduoduo.com")
PRODUCT_PROMOTION_CREATE_URL_PARTS = (
    "/marketing/main/create",
    "/create/double",
    "/mms/promotion/create",
    "/promotion/create",
)
PROMOTION_OVERVIEW_LINK = "https://yingxiao.pinduoduo.com/mains/promotionOverview"
YINGXIAO_PROMOTION_OVERVIEW_URLS = (
    "https://yingxiao.pinduoduo.com/mains/promotionOverview",
    "https://yingxiao.pinduoduo.com/",
)

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
# 仅用于「推广商品 (0)」表头计数；底部帮助文案「若未查询到目标商品…」在有商品时也会出现，不能作为空结果依据
PROMOTION_SEARCH_ZERO_COUNT_MARKERS = ("推广商品 (0)", "推广商品(0)")
ROI_BID_MODAL_MARKERS = ("净目标投产比", "极速起量")
ROI_BID_PROBE_START = 10
ROI_BID_PROBE_STEP = 10
ROI_BID_PROBE_MAX = 200
ROI_BID_LIMIT_PRICE_PATTERN = re.compile(r"请降低至\s*([\d.]+)\s*及以下")
GLOBAL_BOOST_CHECKBOX_TESTID = "create_goods_additional_max_cost_checkbox"
GLOBAL_BOOST_CHECKBOX_MARKERS = (
    "全局优选起量",
    "全店优选起量",
    "优选起量",
    "起量花费比例",
)
_PROMOTION_SEARCH_ZERO_COUNT_JSON = json.dumps(list(PROMOTION_SEARCH_ZERO_COUNT_MARKERS))
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


def _is_yingxiao_promotion_page(page: DpPage) -> bool:
    return "yingxiao.pinduoduo.com" in _page_url(page)


def _is_promotion_overview_page(page: DpPage) -> bool:
    """推广平台概况页（yingxiao）：商品推广 Tab + 新建推广。"""
    if _is_page_not_found(page):
        return False
    if not _is_yingxiao_promotion_page(page):
        return False
    url = _page_url(page)
    text = _body_text(page)
    if not text:
        return False
    has_overview_context = (
        "promotionOverview" in url
        or "商品推广" in text
        or "实时概况" in text
        or "推广平台" in text
    )
    if not has_overview_context:
        return False
    has_product_tab = "商品推广" in text
    has_create_entry = "新建推广" in text
    has_overview_stats = any(
        marker in text for marker in ("推广中", "余额不足", "实时概况", "账户余额", "数据总览")
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
        score += 200
    if "promotionOverview" in url:
        score += 150
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
    if "mms.pinduoduo.com" in url and "yingxiao" not in url:
        score -= 200
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

            function findProductQueryInput() {
                const queryBtn = root.querySelector('button[data-testid="QueryPanel_confirm"]');
                if (queryBtn) {
                    const panel = queryBtn.closest('div, form, section') || root;
                    const panelInputs = Array.from(panel.querySelectorAll('input'))
                        .filter(isVisible)
                        .filter((el) => el.type !== 'checkbox');
                    if (panelInputs.length) return panelInputs[0];
                }
                const labels = Array.from(root.querySelectorAll('label, span, div, p'))
                    .filter(isVisible)
                    .filter((el) => {
                        const text = norm(el.innerText || el.textContent || '');
                        return text === '商品' || text === '商品:' || text.startsWith('商品:');
                    });
                for (const label of labels) {
                    const container = label.closest('div, form, section') || label.parentElement;
                    if (!container) continue;
                    const input = container.querySelector('input');
                    if (input && isVisible(input) && input.type !== 'checkbox') return input;
                }
                const inputs = Array.from(root.querySelectorAll('input'))
                    .filter(isVisible)
                    .filter((el) => el.type !== 'checkbox')
                    .filter((el) => {
                        const placeholder = el.getAttribute('placeholder') || '';
                        return placeholder.includes('商品')
                            || placeholder.includes('ID')
                            || placeholder.includes('id');
                    });
                return inputs[0] || null;
            }

            const input = findProductQueryInput();
            if (!input) {
                return { filled: false, reason: 'product_id_input_not_found' };
            }
            setInputValue(input, '');
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


_DRAWER_ROOT_JS = """
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
"""

_READ_PROMOTION_SEARCH_RESULT_JS = (
    _DRAWER_ROOT_JS
    + f"""
const root = drawerRoot();
if (!root) return {{ ready: false, reason: 'add_product_drawer_not_found' }};

const text = (root.innerText || root.textContent || '').replace(/\\s+/g, ' ');
const countMatch = text.match(/推广商品\\s*\\(\\s*(\\d+)\\s*\\)/);
const headerCount = countMatch ? parseInt(countMatch[1], 10) : null;

const queryPanel = root.querySelector('[data-testid="QueryPanel_confirm"]')
    ?.closest('div, form, section');
const resultRoot = root.querySelector(
    'table, [class*="CustomTable"], [class*="GoodsSelection"], [class*="GoodsTable"]'
) || root;

const editIcons = Array.from(resultRoot.querySelectorAll('[data-testid^="editBid_"]'))
    .filter(isVisible);
const bidRows = Array.from(resultRoot.querySelectorAll('[data-testid^="selected_goods_bid_row_"]'))
    .filter(isVisible);
const productRows = Array.from(resultRoot.querySelectorAll('tbody tr'))
    .filter(isVisible)
    .filter((row) => {{
        if (queryPanel && queryPanel.contains(row)) return false;
        const rowText = (row.innerText || row.textContent || '');
        return row.querySelector('input[type="checkbox"]')
            && (/\\d{{10,}}/.test(rowText) || row.querySelector('[data-testid^="editBid_"]'));
    }});

const productIds = [];
const icons = [];
for (const icon of editIcons) {{
    const testid = icon.getAttribute('data-testid') || '';
    const match = testid.match(/editBid_(\\d+)_/);
    const productId = match ? match[1] : '';
    if (!productId) continue;
    if (!productIds.includes(productId)) productIds.push(productId);
    icons.push({{ product_id: productId, testid }});
}}
for (const row of bidRows) {{
    const testid = row.getAttribute('data-testid') || '';
    const match = testid.match(/selected_goods_bid_row_(\\d+)/);
    const productId = match ? match[1] : '';
    if (!productId || productIds.includes(productId)) continue;
    productIds.push(productId);
    const icon = row.querySelector(
        '[data-testid^="editBid_"], [class*="editIcon"], [class*="MultiSuggestBidPop_triggerNode"]'
    );
    if (icon && isVisible(icon)) {{
        icons.push({{
            product_id: productId,
            testid: icon.getAttribute('data-testid') || '',
        }});
    }}
}}
for (const row of productRows) {{
    const rowText = (row.innerText || row.textContent || '');
    const idMatches = rowText.match(/\\d{{10,}}/g) || [];
    for (const productId of idMatches) {{
        if (productIds.includes(productId)) continue;
        productIds.push(productId);
        const icon = row.querySelector(
            '[data-testid^="editBid_"], [class*="editIcon"], [class*="MultiSuggestBidPop_triggerNode"]'
        );
        if (icon && isVisible(icon)) {{
            icons.push({{
                product_id: productId,
                testid: icon.getAttribute('data-testid') || '',
            }});
        }}
    }}
}}

const hasProducts = (headerCount !== null && headerCount > 0)
    || icons.length > 0
    || bidRows.length > 0
    || productRows.length > 0;
const productCount = hasProducts
    ? Math.max(productIds.length, icons.length, productRows.length, headerCount || 0)
    : 0;
const empty = headerCount === 0 || !hasProducts;
return {{
    ready: true,
    empty,
    product_count: productCount,
    product_ids: productIds,
    edit_icons: icons,
    header_count: headerCount,
    has_products: hasProducts,
    product_row_count: productRows.length,
    text_preview: text.slice(0, 220),
}};
"""
)


def _parse_promotion_header_count(text: str) -> int | None:
    match = re.search(r"推广商品\s*\(\s*(\d+)\s*\)", str(text or ""))
    if not match:
        return None
    return int(match.group(1))


def _is_promotion_search_empty_text(text: str) -> bool:
    """仅当表头明确为「推广商品 (0)」时判定为空；忽略底部帮助文案。"""
    count = _parse_promotion_header_count(text)
    if count is not None:
        return count == 0
    return False


def _is_promotion_search_result_empty(state: dict[str, Any]) -> bool:
    header_count = state.get("header_count")
    if header_count is not None:
        return int(header_count) == 0
    if state.get("edit_icons"):
        return False
    if state.get("product_ids"):
        return False
    if int(state.get("product_row_count") or 0) > 0:
        return False
    return not bool(state.get("has_products"))


def _is_promotion_search_empty_page(page: DpPage) -> bool:
    return _is_promotion_search_empty_text(_body_text(page))


def _read_promotion_search_result(page: DpPage) -> dict[str, Any]:
    """读取添加推广商品抽屉内的查询结果（商品行 / 空状态）。"""
    try:
        result = page.run_js(_READ_PROMOTION_SEARCH_RESULT_JS) or {
            "ready": False,
            "reason": "search_result_js_failed",
        }
    except Exception as exc:
        result = {"ready": False, "reason": _safe_exc(exc)}

    if result.get("ready"):
        return result

    text = _body_text(page)
    header_count = _parse_promotion_header_count(text)
    if header_count is not None and header_count == 0:
        return {
            "ready": True,
            "empty": True,
            "product_count": 0,
            "product_ids": [],
            "edit_icons": [],
            "header_count": header_count,
            "has_products": False,
            "source": "body_text_fallback",
        }
    return result


def _wait_promotion_search_result(page: DpPage, timeout: int = 15) -> dict[str, Any]:
    """等待查询结果渲染完成（有商品行或明确空状态）。"""
    last_state: dict[str, Any] = {}
    for _ in range(timeout):
        last_state = _read_promotion_search_result(page)
        if not last_state.get("ready"):
            time.sleep(1)
            continue
        if last_state.get("has_products") or int(last_state.get("product_count") or 0) > 0:
            return last_state
        if _is_promotion_search_result_empty(last_state):
            return last_state
        time.sleep(1)
    return last_state


def _is_roi_bid_modal_open(page: DpPage) -> bool:
    try:
        return bool(
            page.run_js(
                """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 20 && r.height > 20
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                const roots = Array.from(document.querySelectorAll(
                    '[class*="MultiSuggestBidPop"], [class*="SuggestBid"], [role="dialog"], .anq-modal, .anq-popover'
                )).filter(isVisible);
                for (const root of roots) {
                    const text = (root.innerText || root.textContent || '');
                    if (text.includes('净目标投产比')) return true;
                }
                const bodyText = document.body?.innerText || '';
                return bodyText.includes('净目标投产比')
                    && (bodyText.includes('确定') || bodyText.includes('极速起量'));
                """
            )
        )
    except Exception:
        return False


def _wait_roi_bid_modal(page: DpPage, timeout: int = 10) -> dict[str, Any]:
    for _ in range(timeout):
        if _is_roi_bid_modal_open(page):
            return {"ready": True}
        time.sleep(1)
    return {"ready": False, "reason": "roi_bid_modal_not_found"}


def _close_roi_bid_modal(page: DpPage) -> dict[str, Any]:
    """关闭净目标投产比弹层，便于继续点击下一个商品的小笔。"""
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
        const roots = Array.from(document.querySelectorAll(
            '[class*="MultiSuggestBidPop"], [class*="SuggestBid"], [role="dialog"], .anq-modal, .anq-popover'
        )).filter(isVisible)
            .filter((el) => (el.innerText || el.textContent || '').includes('净目标投产比'));
        if (!roots.length) {
            return { closed: false, reason: 'roi_bid_modal_not_open' };
        }
        const root = roots[roots.length - 1];
        const buttons = Array.from(root.querySelectorAll('button, span, a'))
            .filter(isVisible);
        for (const label of ['取消', '关闭']) {
            const btn = buttons.find((el) => norm(el.innerText || el.textContent || '') === label);
            if (btn) {
                btn.click();
                return { closed: true, method: 'click_' + label };
            }
        }
        const closeIcon = root.querySelector('[aria-label="Close"], [aria-label="关闭"], .anq-modal-close');
        if (closeIcon && isVisible(closeIcon)) {
            closeIcon.click();
            return { closed: true, method: 'close_icon' };
        }
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        return { closed: true, method: 'escape_key' };
        """
    ) or {"closed": False, "reason": "close_roi_modal_js_failed"}
    if result.get("closed"):
        time.sleep(1)
    return result


_ROI_MODAL_JS = """
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

function roiModalRoot() {
    const roots = Array.from(document.querySelectorAll(
        '[class*="MultiSuggestBidPop"], [class*="SuggestBid"], [class*="MultiSuggestBidEditor"], .anq-popover, .anq-modal, [role="dialog"]'
    )).filter(isVisible);
    const hits = roots.filter((el) => {
        const text = (el.innerText || el.textContent || '');
        return text.includes('净目标投产比')
            || text.includes('目标投产比')
            || !!el.querySelector(
                'input[data-testid="CustomInputForBar"], input[data-testid="customInputNumber"], input[data-testid="CustomInputNumber"]'
            );
    });
    if (hits.length) return hits[hits.length - 1];
    return roots.length ? roots[roots.length - 1] : null;
}

function findBidInput(root) {
    if (!root) return null;
    const selectors = [
        'input[data-testid="CustomInputForBar"]',
        'input[data-testid="customInputNumber"]',
        'input[data-testid="CustomInputNumber"]',
        'input.anq-input',
        'input.ant-input',
    ];
    for (const selector of selectors) {
        const input = root.querySelector(selector);
        if (input && isVisible(input)) return input;
    }
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
    input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
}
"""


def _parse_roi_bid_limit_price(text: str) -> str | None:
    match = ROI_BID_LIMIT_PRICE_PATTERN.search(str(text or ""))
    if not match:
        return None
    return str(match.group(1)).strip()


def _read_roi_bid_limit_hint(page: DpPage, product_id: str = "") -> dict[str, Any]:
    """读取净目标投产比弹层中「请降低至 X 及以下」提示。"""
    try:
        result = page.run_js(
            _ROI_MODAL_JS
            + """
            (productId) => {
                const root = roiModalRoot();
                if (!root) return { found: false, reason: 'roi_modal_not_found' };
                const text = (root.innerText || root.textContent || '').replace(/\\s+/g, ' ');
                const patterns = [
                    /请降低至\\s*([\\d.]+)\\s*及以下/,
                    /降低至\\s*([\\d.]+)/,
                ];
                for (const pattern of patterns) {
                    const match = text.match(pattern);
                    if (match) {
                        return {
                            found: true,
                            price: match[1],
                            text_preview: text.slice(0, 240),
                            source: 'modal_text',
                        };
                    }
                }
                const errorNodes = Array.from(root.querySelectorAll(
                    '[class*="Error"], [class*="error"], [class*="warning"], [class*="Tips"], [class*="tip"]'
                )).filter(isVisible);
                for (const node of errorNodes) {
                    const nodeText = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ');
                    for (const pattern of patterns) {
                        const match = nodeText.match(pattern);
                        if (match) {
                            return {
                                found: true,
                                price: match[1],
                                text_preview: nodeText.slice(0, 240),
                                source: 'error_node',
                            };
                        }
                    }
                }
                return { found: false, text_preview: text.slice(0, 240) };
            }
            """,
            product_id,
        ) or {"found": False, "reason": "read_roi_limit_js_failed"}
    except Exception as exc:
        result = {"found": False, "reason": _safe_exc(exc)}

    if not result.get("found"):
        body_price = _parse_roi_bid_limit_price(_body_text(page))
        if body_price:
            result = {"found": True, "price": body_price, "source": "body_text_fallback"}
    return result


def _fill_roi_bid_input(page: DpPage, value: str, product_id: str = "") -> dict[str, Any]:
    """在净目标投产比弹层输入出价。"""
    bid_value = str(value or "").strip()
    if not bid_value:
        return {"filled": False, "reason": "empty_bid_value"}

    result = page.run_js(
        _ROI_MODAL_JS
        + """
        (bidValue) => {
            const root = roiModalRoot();
            if (!root) return { filled: false, reason: 'roi_modal_not_found' };
            const input = findBidInput(root);
            if (!input) return { filled: false, reason: 'roi_bid_input_not_found' };
            setInputValue(input, bidValue);
            return {
                filled: true,
                value: input.value,
                testid: input.getAttribute('data-testid') || '',
                method: 'js_roi_bid_input',
            };
        }
        """,
        bid_value,
    ) or {"filled": False, "reason": "fill_roi_bid_js_failed"}

    if result.get("filled"):
        time.sleep(1.2)
        return result

    try:
        raw_page = getattr(page, "_page")
        for selector in (
            'input[data-testid="CustomInputForBar"]',
            'input[data-testid="customInputNumber"]',
            'input[data-testid="CustomInputNumber"]',
        ):
            loc = raw_page.locator(selector).last
            if loc.count():
                loc.click(timeout=3_000)
                loc.fill(bid_value, timeout=5_000)
                time.sleep(1.2)
                return {
                    "filled": True,
                    "value": bid_value,
                    "method": f"playwright_{selector}",
                }
    except Exception as exc:
        return {"filled": False, "reason": _safe_exc(exc), **result}
    return result


def _probe_roi_bid_limit_price(
    page: DpPage,
    product_id: str,
    account_id: str,
) -> dict[str, Any]:
    """输入 10、20、30… 直到出现「请降低至 X 及以下」提示。"""
    probe_attempts: list[dict[str, Any]] = []
    suggested_price: str | None = None

    for probe_value in range(ROI_BID_PROBE_START, ROI_BID_PROBE_MAX + 1, ROI_BID_PROBE_STEP):
        fill_result = _fill_roi_bid_input(page, str(probe_value), product_id)
        if not fill_result.get("filled"):
            return {
                "status": "failed",
                "step": "fill_roi_bid_probe",
                "error": fill_result.get("reason") or "无法填写净目标投产比探测值",
                "probe_value": probe_value,
                "fill_result": fill_result,
                "probe_attempts": probe_attempts,
            }

        hint = _read_roi_bid_limit_hint(page, product_id)
        attempt = {"probe_value": probe_value, "hint": hint, "fill_result": fill_result}
        probe_attempts.append(attempt)
        print(
            f"[{account_id}] 商品 {product_id} 探测出价 {probe_value}，"
            f"提示: {hint.get('price') or '未出现'}",
            flush=True,
        )
        if hint.get("found") and hint.get("price"):
            suggested_price = str(hint.get("price")).strip()
            break

    if not suggested_price:
        return {
            "status": "failed",
            "step": "probe_roi_bid_limit",
            "error": f"输入至 {ROI_BID_PROBE_MAX} 仍未出现净目标投产比上限提示",
            "probe_attempts": probe_attempts,
            "product_id": product_id,
        }

    return {
        "status": "success",
        "suggested_price": suggested_price,
        "probe_attempts": probe_attempts,
        "product_id": product_id,
    }


def _confirm_roi_bid_modal(page: DpPage, product_id: str) -> dict[str, Any]:
    """点击净目标投产比弹层「确定」。"""
    pid = str(product_id or "").strip()
    result = page.run_js(
        _ROI_MODAL_JS
        + """
        (productId) => {
            const root = roiModalRoot();
            if (!root) return { clicked: false, reason: 'roi_modal_not_found' };

            const testidBtn = productId
                ? root.querySelector(`button[data-testid="confirm_${productId}"]`)
                : null;
            if (testidBtn && isVisible(testidBtn)) {
                testidBtn.click();
                return {
                    clicked: true,
                    method: 'confirm_testid',
                    testid: testidBtn.getAttribute('data-testid') || '',
                };
            }

            const buttons = Array.from(root.querySelectorAll('button'))
                .filter(isVisible)
                .filter((btn) => norm(btn.innerText || btn.textContent || '') === '确定');
            if (buttons.length) {
                const btn = buttons[buttons.length - 1];
                btn.click();
                return {
                    clicked: true,
                    method: 'confirm_text_button',
                    testid: btn.getAttribute('data-testid') || '',
                };
            }
            return { clicked: false, reason: 'roi_confirm_button_not_found' };
        }
        """,
        pid,
    ) or {"clicked": False, "reason": "confirm_roi_bid_js_failed"}

    if result.get("clicked"):
        time.sleep(1.5)
        return result

    try:
        raw_page = getattr(page, "_page")
        btn = raw_page.locator(f'button[data-testid="confirm_{pid}"]').last
        if not btn.count():
            btn = raw_page.locator(
                '[class*="MultiSuggestBidPop"] button:has-text("确定"), '
                '[class*="SuggestBid"] button:has-text("确定")'
            ).last
        btn.wait_for(state="visible", timeout=5_000)
        btn.click(timeout=5_000)
        time.sleep(1.5)
        return {"clicked": True, "method": "playwright_confirm", "product_id": pid}
    except Exception as exc:
        return {"clicked": False, "reason": _safe_exc(exc), **result}


def _configure_roi_bid_for_product(
    page: DpPage,
    product_id: str,
    account_id: str,
) -> dict[str, Any]:
    """探测上限价 → 填入建议价 → 点击确定。"""
    pid = str(product_id or "").strip()
    probe_result = _probe_roi_bid_limit_price(page, pid, account_id)
    if probe_result.get("status") != "success":
        return {
            "status": "failed",
            "step": probe_result.get("step") or "probe_roi_bid_limit",
            "error": probe_result.get("error") or "探测净目标投产比失败",
            "product_id": pid,
            "probe_result": probe_result,
        }

    suggested_price = str(probe_result.get("suggested_price") or "").strip()
    fill_result = _fill_roi_bid_input(page, suggested_price, pid)
    if not fill_result.get("filled"):
        return {
            "status": "failed",
            "step": "fill_roi_bid_final",
            "error": fill_result.get("reason") or f"无法填入建议出价 {suggested_price}",
            "product_id": pid,
            "suggested_price": suggested_price,
            "probe_result": probe_result,
            "fill_result": fill_result,
        }

    confirm_result = _confirm_roi_bid_modal(page, pid)
    if not confirm_result.get("clicked"):
        return {
            "status": "failed",
            "step": "confirm_roi_bid",
            "error": confirm_result.get("reason") or "无法点击净目标投产比确定",
            "product_id": pid,
            "suggested_price": suggested_price,
            "probe_result": probe_result,
            "fill_result": fill_result,
            "confirm_result": confirm_result,
        }

    print(
        f"[{account_id}] 商品 {pid} 净目标投产比已设为 {suggested_price}",
        flush=True,
    )
    return {
        "status": "success",
        "product_id": pid,
        "suggested_price": suggested_price,
        "probe_result": probe_result,
        "fill_result": fill_result,
        "confirm_result": confirm_result,
    }


_READ_GLOBAL_BOOST_CHECKBOX_JS = f"""
function isVisible(el) {{
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none'
        && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}}

function norm(text) {{
    return (text || '').replace(/\\s+/g, '').trim();
}}

function scrollDrawerFooter() {{
    const bodies = Array.from(document.querySelectorAll(
        '.anq-drawer-body, .anq-drawer-content, .anq-drawer-content-wrapper, [class*="GoodsSelection"]'
    ));
    for (const body of bodies) {{
        try {{ body.scrollTop = body.scrollHeight; }} catch (e) {{}}
    }}
    window.scrollTo(0, document.body.scrollHeight);
}}

function findBoostCheckboxInput() {{
    scrollDrawerFooter();

    const testidSelectors = [
        'input[data-testid="{GLOBAL_BOOST_CHECKBOX_TESTID}"]',
        'input[data-testid*="additional_max_cost"]',
        'input[data-testid*="max_cost_checkbox"]',
    ];
    for (const selector of testidSelectors) {{
        const nodes = Array.from(document.querySelectorAll(selector)).filter(isVisible);
        if (nodes.length) return nodes[nodes.length - 1];
    }}

    const drawerScopes = Array.from(document.querySelectorAll(
        '.anq-drawer-wrapper, .anq-drawer, .anq-drawer-content-wrapper, [class*="GoodsSelection"], [class*="anq-drawer"]'
    )).filter(isVisible);
    for (const scope of drawerScopes) {{
        for (const selector of testidSelectors) {{
            const node = scope.querySelector(selector);
            if (node && isVisible(node)) return node;
        }}
    }}

    const markers = {json.dumps(list(GLOBAL_BOOST_CHECKBOX_MARKERS))};
    const textHits = Array.from(document.querySelectorAll('span, div, label, p'))
        .filter(isVisible)
        .filter((el) => {{
            const text = norm(el.innerText || el.textContent || '');
            if (!text || text.length > 120) return false;
            return markers.some((marker) => text.includes(marker));
        }});
    for (const hit of textHits) {{
        let node = hit;
        for (let depth = 0; depth < 6 && node; depth += 1) {{
            const input = node.querySelector?.('input[type="checkbox"]');
            if (input && isVisible(input)) return input;
            const prev = node.previousElementSibling;
            if (prev) {{
                const prevInput = prev.querySelector?.('input[type="checkbox"]');
                if (prevInput && isVisible(prevInput)) return prevInput;
            }}
            const parentInput = node.parentElement?.querySelector?.('input[type="checkbox"]');
            if (parentInput && isVisible(parentInput)) return parentInput;
            node = node.parentElement;
        }}
    }}

    const footerCheckboxes = Array.from(document.querySelectorAll(
        '.anq-drawer-footer input[type="checkbox"], .anq-drawer-wrapper input[type="checkbox"]'
    )).filter(isVisible);
    if (footerCheckboxes.length) return footerCheckboxes[footerCheckboxes.length - 1];

    return null;
}}

function isCheckboxChecked(input) {{
    if (!input) return false;
    if (input.type === 'checkbox') return !!input.checked;
    const wrap = input.closest('.anq-checkbox-wrapper');
    return !!(wrap && wrap.classList.contains('anq-checkbox-wrapper-checked'));
}}

const input = findBoostCheckboxInput();
if (!input) {{
    return {{ found: false, reason: 'global_boost_checkbox_not_found' }};
}}
const label = input.closest('label.anq-checkbox-wrapper, label');
return {{
    found: true,
    checked: isCheckboxChecked(input),
    testid: input.getAttribute('data-testid') || '',
    label_preview: ((label?.innerText || label?.textContent || '') + '').replace(/\\s+/g, ' ').slice(0, 80),
}};
"""


_UNCHECK_GLOBAL_BOOST_CHECKBOX_JS = f"""
function isVisible(el) {{
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none'
        && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}}

function norm(text) {{
    return (text || '').replace(/\\s+/g, '').trim();
}}

function scrollDrawerFooter() {{
    const bodies = Array.from(document.querySelectorAll(
        '.anq-drawer-body, .anq-drawer-content, .anq-drawer-content-wrapper, [class*="GoodsSelection"]'
    ));
    for (const body of bodies) {{
        try {{ body.scrollTop = body.scrollHeight; }} catch (e) {{}}
    }}
    window.scrollTo(0, document.body.scrollHeight);
}}

function findBoostCheckboxInput() {{
    scrollDrawerFooter();
    const testidSelectors = [
        'input[data-testid="{GLOBAL_BOOST_CHECKBOX_TESTID}"]',
        'input[data-testid*="additional_max_cost"]',
        'input[data-testid*="max_cost_checkbox"]',
    ];
    for (const selector of testidSelectors) {{
        const nodes = Array.from(document.querySelectorAll(selector)).filter(isVisible);
        if (nodes.length) return nodes[nodes.length - 1];
    }}
    const markers = {json.dumps(list(GLOBAL_BOOST_CHECKBOX_MARKERS))};
    const textHits = Array.from(document.querySelectorAll('span, div, label, p'))
        .filter(isVisible)
        .filter((el) => {{
            const text = norm(el.innerText || el.textContent || '');
            if (!text || text.length > 120) return false;
            return markers.some((marker) => text.includes(marker));
        }});
    for (const hit of textHits) {{
        let node = hit;
        for (let depth = 0; depth < 6 && node; depth += 1) {{
            const input = node.querySelector?.('input[type="checkbox"]');
            if (input && isVisible(input)) return input;
            const prev = node.previousElementSibling;
            if (prev) {{
                const prevInput = prev.querySelector?.('input[type="checkbox"]');
                if (prevInput && isVisible(prevInput)) return prevInput;
            }}
            node = node.parentElement;
        }}
    }}
    return null;
}}

function isCheckboxChecked(input) {{
    if (!input) return false;
    if (input.type === 'checkbox') return !!input.checked;
    const wrap = input.closest('.anq-checkbox-wrapper');
    return !!(wrap && wrap.classList.contains('anq-checkbox-wrapper-checked'));
}}

function clickCheckbox(input) {{
    const label = input.closest('label.anq-checkbox-wrapper, label');
    const target = label || input;
    target.scrollIntoView({{ block: 'center', inline: 'nearest' }});
    target.click();
}}

const input = findBoostCheckboxInput();
if (!input) {{
    return {{ changed: false, found: false, reason: 'global_boost_checkbox_not_found' }};
}}

const wasChecked = isCheckboxChecked(input);
if (!wasChecked) {{
    return {{
        changed: false,
        found: true,
        checked: false,
        already_unchecked: true,
        testid: input.getAttribute('data-testid') || '',
    }};
}}

clickCheckbox(input);
if (isCheckboxChecked(input)) {{
    input.click();
    const inner = input.closest('.anq-checkbox');
    if (inner) inner.click();
}}
return {{
    changed: true,
    found: true,
    checked: isCheckboxChecked(input),
    was_checked: wasChecked,
    testid: input.getAttribute('data-testid') || '',
    method: 'click_checkbox_label',
}};
"""


def _read_global_boost_checkbox_state(page: DpPage) -> dict[str, Any]:
    """读取「全局/全店优选起量」勾选状态。"""
    try:
        return page.run_js(_READ_GLOBAL_BOOST_CHECKBOX_JS) or {
            "found": False,
            "reason": "read_global_boost_checkbox_js_failed",
        }
    except Exception as exc:
        return {"found": False, "reason": _safe_exc(exc)}


def _uncheck_global_boost_checkbox_playwright(page: DpPage) -> dict[str, Any]:
    """Playwright 定位并取消勾选优选起量复选框。"""
    try:
        raw_page = getattr(page, "_page")
        loc = None
        for selector in (
            f'input[data-testid="{GLOBAL_BOOST_CHECKBOX_TESTID}"]',
            'input[data-testid*="additional_max_cost"]',
            'input[data-testid*="max_cost_checkbox"]',
        ):
            candidate = raw_page.locator(selector).last
            if candidate.count():
                loc = candidate
                break

        drawer = raw_page.locator(
            '.anq-drawer-wrapper:has-text("添加推广商品"), '
            '[class*="GoodsSelection"]:has-text("添加推广商品")'
        ).last
        if loc is None and drawer.count():
            for selector in (
                f'input[data-testid="{GLOBAL_BOOST_CHECKBOX_TESTID}"]',
                'input[data-testid*="additional_max_cost"]',
            ):
                candidate = drawer.locator(selector).last
                if candidate.count():
                    loc = candidate
                    break
            if loc is None:
                text_row = drawer.locator('div, span, p, label').filter(has_text='优选起量').last
                if text_row.count():
                    candidate = text_row.locator('xpath=ancestor::*[position()<=5]//input[@type="checkbox"]').last
                    if candidate.count():
                        loc = candidate
                    else:
                        candidate = text_row.locator('xpath=preceding::input[@type="checkbox"][1]').last
                        if candidate.count():
                            loc = candidate

        if loc is None or not loc.count():
            label = raw_page.locator(
                f'label.anq-checkbox-wrapper:has(input[data-testid="{GLOBAL_BOOST_CHECKBOX_TESTID}"])'
            ).last
            if label.count():
                loc = label.locator('input[type="checkbox"]').first

        if loc is None or not loc.count():
            return {"found": False, "reason": "global_boost_checkbox_not_found"}

        loc.scroll_into_view_if_needed(timeout=5_000)
        was_checked = loc.is_checked()
        if not was_checked:
            return {
                "found": True,
                "unchecked": True,
                "already_unchecked": True,
                "method": "playwright_checkbox",
            }

        label = loc.locator('xpath=ancestor::label[contains(@class,"checkbox-wrapper")]').last
        if label.count():
            label.click(timeout=5_000)
        else:
            loc.click(force=True, timeout=5_000)

        time.sleep(0.8)
        if loc.is_checked():
            loc.click(force=True, timeout=3_000)
            time.sleep(0.5)

        return {
            "found": True,
            "unchecked": not loc.is_checked(),
            "was_checked": was_checked,
            "method": "playwright_checkbox_click",
        }
    except Exception as exc:
        return {"found": False, "reason": _safe_exc(exc)}


def _wait_global_boost_checkbox(page: DpPage, timeout: int = 12) -> dict[str, Any]:
    last_state: dict[str, Any] = {}
    for _ in range(timeout):
        last_state = _read_global_boost_checkbox_state(page)
        if last_state.get("found"):
            return last_state
        time.sleep(1)
    return last_state


def _ensure_global_boost_checkbox_unchecked(
    page: DpPage,
    account_id: str,
    *,
    max_attempts: int = 5,
) -> dict[str, Any]:
    """确保「开启全局/全店优选起量」复选框为取消勾选状态。"""
    _dismiss_message_popup(page)
    page.run_js(
        """
        const bodies = Array.from(document.querySelectorAll(
            '.anq-drawer-body, .anq-drawer-content, .anq-drawer-content-wrapper'
        ));
        for (const body of bodies) {
            try { body.scrollTop = body.scrollHeight; } catch (e) {}
        }
        """
    )
    time.sleep(0.5)

    last_state = _wait_global_boost_checkbox(page, timeout=12)
    attempts: list[dict[str, Any]] = []

    for attempt_index in range(max_attempts):
        state = last_state if attempt_index == 0 and last_state.get("found") else _read_global_boost_checkbox_state(page)
        if not state.get("found"):
            pw_probe = _uncheck_global_boost_checkbox_playwright(page)
            attempts.append({"attempt": attempt_index + 1, "playwright_probe": pw_probe})
            if pw_probe.get("found") and (pw_probe.get("unchecked") or pw_probe.get("already_unchecked")):
                print(f"[{account_id}] 已通过 Playwright 取消勾选全局优选起量", flush=True)
                return {
                    "status": "success",
                    "unchecked": True,
                    "attempts": attempts,
                    "final_state": pw_probe,
                    "method": "playwright_direct",
                }
            time.sleep(1)
            last_state = _read_global_boost_checkbox_state(page)
            continue

        last_state = state
        if not state.get("checked"):
            print(f"[{account_id}] 全局优选起量已处于取消勾选状态", flush=True)
            return {
                "status": "success",
                "unchecked": True,
                "already_unchecked": True,
                "attempts": attempts,
                "final_state": state,
            }

        uncheck_result = page.run_js(_UNCHECK_GLOBAL_BOOST_CHECKBOX_JS) or {
            "found": False,
            "reason": "uncheck_global_boost_checkbox_js_failed",
        }
        attempts.append({"attempt": attempt_index + 1, "uncheck_result": uncheck_result})
        time.sleep(0.8)

        verify_state = _read_global_boost_checkbox_state(page)
        if verify_state.get("found") and not verify_state.get("checked"):
            print(f"[{account_id}] 已取消勾选全局优选起量", flush=True)
            return {
                "status": "success",
                "unchecked": True,
                "attempts": attempts,
                "final_state": verify_state,
            }

        pw_result = _uncheck_global_boost_checkbox_playwright(page)
        attempts.append({"attempt": attempt_index + 1, "playwright_uncheck": pw_result})
        if pw_result.get("found") and pw_result.get("unchecked"):
            print(f"[{account_id}] 已通过 Playwright 取消勾选全局优选起量", flush=True)
            return {
                "status": "success",
                "unchecked": True,
                "attempts": attempts,
                "final_state": pw_result,
                "method": "playwright_fallback",
            }

        last_state = _read_global_boost_checkbox_state(page)
        time.sleep(0.5)

    if last_state.get("found") and last_state.get("checked"):
        return {
            "status": "failed",
            "step": "ensure_global_boost_unchecked",
            "error": "无法取消勾选「全局/全店优选起量」，请手动关闭后重试",
            "attempts": attempts,
            "final_state": last_state,
        }

    return {
        "status": "failed",
        "step": "ensure_global_boost_unchecked",
        "error": last_state.get("reason") or "未找到全局/全店优选起量复选框",
        "attempts": attempts,
        "final_state": last_state,
        "body_preview": _body_text(page)[-400:],
    }


def _click_promotion_edit_bid_icon(page: DpPage, product_id: str) -> dict[str, Any]:
    """点击指定商品行的净目标投产比编辑小笔。"""
    pid = str(product_id or "").strip()
    if not pid:
        return {"clicked": False, "reason": "empty_product_id"}

    result = page.run_js(
        _DRAWER_ROOT_JS
        + """
        (productId) => {
            const root = drawerRoot();
            if (!root) return { clicked: false, reason: 'add_product_drawer_not_found' };

            const selectors = [
                `[data-testid="editBid_${productId}_create_create"]`,
                `[data-testid^="editBid_${productId}_"]`,
                `[data-testid="selected_goods_bid_row_${productId}"] [data-testid^="editBid_"]`,
                `[data-testid="selected_goods_bid_row_${productId}"] [class*="editIcon"]`,
            ];
            let icon = null;
            for (const selector of selectors) {
                const found = root.querySelector(selector);
                if (found && isVisible(found)) {
                    icon = found;
                    break;
                }
            }
            if (!icon) {
                const rows = Array.from(root.querySelectorAll('tbody tr, [data-testid^="selected_goods_bid_row_"]'))
                    .filter(isVisible)
                    .filter((row) => (row.innerText || row.textContent || '').includes(productId));
                for (const row of rows) {
                    const candidate = row.querySelector(
                        '[data-testid^="editBid_"], [class*="editIcon"], [class*="MultiSuggestBidPop_triggerNode"], [class*="PromotionSetting"] span[role="img"]'
                    );
                    if (candidate && isVisible(candidate)) {
                        icon = candidate;
                        break;
                    }
                }
            }
            if (!icon) {
                const icons = Array.from(root.querySelectorAll(
                    '[data-testid^="editBid_"], [class*="editIcon"], [class*="MultiSuggestBidPop_triggerNode"]'
                ))
                    .filter(isVisible)
                    .filter((el) => (el.getAttribute('data-testid') || '').includes(productId));
                icon = icons[0] || null;
            }
            if (!icon) {
                return { clicked: false, reason: 'edit_bid_icon_not_found', product_id: productId };
            }
            icon.scrollIntoView({ block: 'center', inline: 'nearest' });
            icon.click();
            return {
                clicked: true,
                product_id: productId,
                testid: icon.getAttribute('data-testid') || '',
                method: 'edit_bid_icon_click',
            };
        }
        """,
        pid,
    ) or {"clicked": False, "reason": "edit_bid_icon_js_failed", "product_id": pid}

    if result.get("clicked"):
        time.sleep(1.5)
        return result

    try:
        raw_page = getattr(page, "_page")
        drawer = raw_page.locator(
            '.anq-drawer-content-wrapper:has-text("添加推广商品"), '
            '[class*="GoodsSelection"]:has-text("添加推广商品")'
        ).last
        icon = drawer.locator(f'[data-testid="editBid_{pid}_create_create"]').first
        if not icon.count():
            icon = drawer.locator(f'[data-testid^="editBid_{pid}_"]').first
        if not icon.count():
            icon = drawer.locator(f'[data-testid="selected_goods_bid_row_{pid}"] [class*="editIcon"]').first
        if not icon.count():
            icon = drawer.locator(f'tr:has-text("{pid}") [class*="editIcon"], tr:has-text("{pid}") [data-testid^="editBid_"]').first
        icon.wait_for(state="visible", timeout=5_000)
        icon.click(timeout=5_000)
        time.sleep(1.5)
        return {"clicked": True, "product_id": pid, "method": "playwright_edit_bid_icon"}
    except Exception as exc:
        return {
            "clicked": False,
            "reason": _safe_exc(exc),
            "product_id": pid,
            **result,
        }


def _click_promotion_edit_bid_icons(
    page: DpPage,
    account_id: str,
    requested_product_ids: list[str],
) -> dict[str, Any]:
    """查询后有商品则依次点击小笔，并等待净目标投产比弹层出现。"""
    requested = [str(item).strip() for item in requested_product_ids if str(item).strip()]

    search_state = _wait_promotion_search_result(page, timeout=15)
    if not search_state.get("ready"):
        return {
            "status": "failed",
            "step": "read_promotion_search_result",
            "error": search_state.get("reason") or "无法读取查询结果",
            "search_state": search_state,
        }

    if _is_promotion_search_result_empty(search_state):
        return {
            "status": "failed",
            "step": "promotion_search_empty",
            "error": "未查询到目标商品，请确认商品 ID 是否正确或是否已创建推广",
            "search_state": search_state,
            "requested_product_ids": requested,
        }

    found_ids = [str(item) for item in (search_state.get("product_ids") or []) if str(item).strip()]
    if not found_ids:
        edit_icons = search_state.get("edit_icons") or []
        found_ids = [str(item.get("product_id") or "").strip() for item in edit_icons]
        found_ids = [item for item in found_ids if item]

    header_count = search_state.get("header_count")
    if not found_ids and header_count is not None and int(header_count) > 0:
        found_ids = list(requested)

    if not found_ids:
        if _is_promotion_search_result_empty(search_state):
            return {
                "status": "failed",
                "step": "promotion_search_empty",
                "error": "未查询到目标商品，请确认商品 ID 是否正确或是否已创建推广",
                "search_state": search_state,
                "requested_product_ids": requested,
            }
        return {
            "status": "failed",
            "step": "promotion_search_no_edit_icon",
            "error": "查询到商品但未找到推广设置小笔图标",
            "search_state": search_state,
            "requested_product_ids": requested,
        }

    missing_ids = [item for item in requested if item not in found_ids]
    if missing_ids:
        print(
            f"[{account_id}] 部分商品未出现在查询结果中: {missing_ids}，将继续处理已找到的 {found_ids}",
            flush=True,
        )

    click_results: list[dict[str, Any]] = []
    for product_id in found_ids:
        click_result = _click_promotion_edit_bid_icon(page, product_id)
        if not click_result.get("clicked"):
            return {
                "status": "failed",
                "step": "click_edit_bid_icon",
                "error": click_result.get("reason") or f"无法点击商品 {product_id} 的推广设置小笔",
                "product_id": product_id,
                "click_results": click_results,
                "search_state": search_state,
                "missing_product_ids": missing_ids,
            }

        modal_wait = _wait_roi_bid_modal(page, timeout=12)
        if not modal_wait.get("ready"):
            return {
                "status": "failed",
                "step": "wait_roi_bid_modal",
                "error": f"点击商品 {product_id} 小笔后未出现净目标投产比弹层",
                "product_id": product_id,
                "click_result": click_result,
                "modal_wait": modal_wait,
                "click_results": click_results,
                "search_state": search_state,
                "missing_product_ids": missing_ids,
            }

        bid_config = _configure_roi_bid_for_product(page, product_id, account_id)
        if bid_config.get("status") != "success":
            return {
                "status": "failed",
                "step": bid_config.get("step") or "configure_roi_bid",
                "error": bid_config.get("error") or f"商品 {product_id} 净目标投产比设置失败",
                "product_id": product_id,
                "click_result": click_result,
                "modal_wait": modal_wait,
                "bid_config": bid_config,
                "click_results": click_results,
                "search_state": search_state,
                "missing_product_ids": missing_ids,
            }

        click_results.append(
            {
                "product_id": product_id,
                "click_result": click_result,
                "modal_wait": modal_wait,
                "bid_config": bid_config,
                "suggested_price": bid_config.get("suggested_price"),
            }
        )
        print(
            f"[{account_id}] 商品 {product_id} 净目标投产比已确认: {bid_config.get('suggested_price')}",
            flush=True,
        )
        time.sleep(1)

    return {
        "status": "success",
        "step": "roi_bid_configured",
        "found_count": len(found_ids),
        "found_product_ids": found_ids,
        "missing_product_ids": missing_ids,
        "configured_prices": {
            item["product_id"]: item.get("suggested_price")
            for item in click_results
        },
        "click_results": click_results,
        "search_state": search_state,
    }


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
        wait_state = _wait_promotion_search_result(page, timeout=15)
        batch_results[-1]["search_state"] = wait_state
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


def _has_new_promotion_button(page: DpPage) -> bool:
    try:
        return bool(
            page.run_js(
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
                const buttons = Array.from(document.querySelectorAll('button')).filter(isVisible);
                return buttons.some((btn) => {
                    const label = norm(btn.innerText || btn.textContent || '');
                    return label === '新建推广'
                        || label === '+新建推广'
                        || label.endsWith('新建推广');
                });
                """
            )
        )
    except Exception:
        return False


def _wait_new_promotion_button(page: DpPage, timeout: int = 15) -> bool:
    for _ in range(timeout):
        if _has_new_promotion_button(page):
            return True
        time.sleep(1)
    return False


def _ensure_yingxiao_promotion_overview_url(
    page: DpPage,
    account_id: str,
    account: AccountConfig | None = None,
) -> bool:
    """确保当前 yingxiao 标签在 promotionOverview 且商品推广 Tab 可见。"""
    if not _is_yingxiao_promotion_page(page):
        return False

    url = _page_url(page)
    if "promotionOverview" not in url:
        try:
            print(f"[{account_id}] 当前 yingxiao 不在概况页，跳转: {PROMOTION_OVERVIEW_LINK}", flush=True)
            page.get(PROMOTION_OVERVIEW_LINK)
            time.sleep(4)
            if is_login_url(_page_url(page)):
                relogin = _ensure_session(page, account, account_id)
                if not relogin.get("logged_in"):
                    return False
                page.get(PROMOTION_OVERVIEW_LINK)
                time.sleep(4)
        except Exception as exc:
            print(f"[{account_id}] 跳转 promotionOverview 异常：{_safe_exc(exc)}", flush=True)
            return False

    _dismiss_message_popup(page)
    _ensure_product_promotion_tab(page)
    if _wait_promotion_overview_page(page, timeout=12):
        return True
    return _wait_new_promotion_button(page, timeout=8)


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


def _wait_yingxiao_promotion_tab(page: DpPage, account_id: str, timeout: int = 15) -> bool:
    """等待 yingxiao 推广概况标签页出现。"""
    for _ in range(timeout):
        _dismiss_message_popup(page)
        _switch_to_latest_tab(page)
        for raw in _live_context_pages(page):
            url = str(getattr(raw, "url", "") or "")
            if "yingxiao.pinduoduo.com" not in url:
                continue
            _bind_page(page, raw)
            try:
                raw.bring_to_front()
            except Exception:
                pass
            time.sleep(0.5)
            if _is_promotion_overview_page(page) or _has_new_promotion_button(page):
                print(f"[{account_id}] 已切换到 yingxiao 推广概况: {url}", flush=True)
                return True
        time.sleep(1)
    return False


def _navigate_yingxiao_promotion_overview(
    page: DpPage,
    account_id: str,
    account: AccountConfig | None = None,
) -> bool:
    """直达 yingxiao 推广概况（与用户手动进入的页面一致）。"""
    for url in YINGXIAO_PROMOTION_OVERVIEW_URLS:
        try:
            print(f"[{account_id}] 尝试打开 yingxiao 推广概况: {url}", flush=True)
            page.get(url)
            time.sleep(4)
            if is_login_url(_page_url(page)):
                relogin = _ensure_session(page, account, account_id)
                if not relogin.get("logged_in"):
                    return False
                page.get(url)
                time.sleep(4)
            _dismiss_message_popup(page)
            if _is_page_not_found(page):
                continue
            if _ensure_yingxiao_promotion_overview_url(page, account_id, account=account):
                return True
        except Exception as exc:
            print(f"[{account_id}] 打开 yingxiao 推广概况异常：{_safe_exc(exc)}", flush=True)
    return False


def _close_mms_tabs_when_yingxiao_ready(page: DpPage, account_id: str) -> dict[str, Any]:
    """已有 yingxiao 推广页时，关闭 mms 商家后台标签。"""
    pages = _live_context_pages(page)
    has_yingxiao = any("yingxiao.pinduoduo.com" in str(getattr(p, "url", "") or "") for p in pages)
    if not has_yingxiao:
        return {"closed": [], "skipped": True}
    closed_urls: list[str] = []
    for item in list(pages):
        url = str(item.url or "")
        if "mms.pinduoduo.com" not in url:
            continue
        try:
            item.close()
            closed_urls.append(url)
            print(f"[{account_id}] 已关闭 mms 标签页: {url}", flush=True)
        except Exception:
            continue
    _focus_best_promotion_page(page, account_id)
    return {"closed": closed_urls, "closed_count": len(closed_urls)}


def _click_sidebar_promotion_overview(page: DpPage) -> dict[str, Any]:
    """商家后台左侧「推广平台 → 推广概况」，会新开 yingxiao 标签页。"""
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

        const yingxiaoLink = Array.from(document.querySelectorAll('a[href]'))
            .filter(isVisible)
            .find((el) => {
                const href = String(el.getAttribute('href') || '');
                const text = norm(el.innerText || el.textContent || '');
                return text === '推广概况'
                    && (href.includes('yingxiao') || href.includes('promotionOverview'));
            });
        if (yingxiaoLink) {
            clickEl(yingxiaoLink);
            return {
                clicked: true,
                method: 'sidebar_yingxiao_href',
                href: yingxiaoLink.getAttribute('href') || '',
            };
        }

        for (const groupLabel of ['推广平台', '流量运营', '推广']) {
            const group = findSidebarItem(groupLabel);
            if (group) clickEl(group);
        }

        const overviewLinks = Array.from(document.querySelectorAll('a[href]'))
            .filter(isVisible)
            .filter((el) => norm(el.innerText || el.textContent || '') === '推广概况');
        if (overviewLinks.length) {
            const link = overviewLinks[0];
            clickEl(link);
            return {
                clicked: true,
                method: 'sidebar_overview_text_link',
                href: link.getAttribute('href') || '',
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
    """进入 yingxiao 推广概况（与用户手动：推广平台 → 推广概况 一致）。"""
    _ensure_session(page, account, account_id)
    _dismiss_message_popup(page)

    print(f"[{account_id}] 从商家后台进入 yingxiao 推广概况", flush=True)

    # 优先走商家后台侧边栏（与用户手动操作一致，会新开 yingxiao 标签页）
    try:
        current_url = _page_url(page)
        if "mms.pinduoduo.com" not in current_url:
            page.get("https://mms.pinduoduo.com/home/")
            time.sleep(2)
        if is_login_url(_page_url(page)):
            relogin = _ensure_session(page, account, account_id)
            if not relogin.get("logged_in"):
                return False
        _dismiss_message_popup(page)
        click_result = _click_sidebar_promotion_overview(page)
        if not click_result.get("clicked"):
            if not _click_text(page, "推广平台", timeout=3):
                _click_text(page, "流量运营", timeout=2)
            time.sleep(1)
            if _click_text(page, "推广概况", timeout=5):
                click_result = {"clicked": True, "method": "text_click"}
            else:
                print(f"[{account_id}] 侧边栏未找到推广概况", flush=True)
        if click_result.get("clicked"):
            time.sleep(2)
            _switch_to_latest_tab(page)
            if _wait_yingxiao_promotion_tab(page, account_id, timeout=20):
                _close_mms_tabs_when_yingxiao_ready(page, account_id)
                if _ensure_yingxiao_promotion_overview_url(page, account_id, account=account):
                    _close_other_promotion_tabs(page, account_id)
                    print(f"[{account_id}] 已通过侧边栏进入 yingxiao 推广概况", flush=True)
                    return True
    except Exception as exc:
        print(f"[{account_id}] 菜单进入推广概况异常：{_safe_exc(exc)}", flush=True)

    if _navigate_yingxiao_promotion_overview(page, account_id, account=account):
        _close_mms_tabs_when_yingxiao_ready(page, account_id)
        _close_other_promotion_tabs(page, account_id)
        return True

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
    """yingxiao 商品推广 Tab 内点击「+ 新建推广」。"""
    _dismiss_message_popup(page)
    if not _is_yingxiao_promotion_page(page):
        _focus_best_promotion_page(page, account_id)
    if not _is_yingxiao_promotion_page(page):
        return {
            "clicked": False,
            "reason": "not_on_yingxiao_promotion_page",
            "current_url": _page_url(page),
        }

    _ensure_product_promotion_tab(page)
    if not _wait_new_promotion_button(page, timeout=12):
        print(
            f"[{account_id}] 等待新建推广按钮超时，当前页: {_page_url(page)}",
            flush=True,
        )

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

        const buttons = Array.from(document.querySelectorAll('button')).filter(isVisible);
        const ranked = [];
        for (const btn of buttons) {
            const label = buttonLabel(btn);
            if (!isNewPromotionLabel(label)) continue;
            if (label.includes('查看全部') || label.includes('一键推广') || label.includes('立即推广')) continue;
            let score = 0;
            if ((btn.className || '').includes('CreatePromotionBtn')) score += 100;
            if (label.startsWith('+') || label.startsWith('＋')) score += 50;
            const rect = btn.getBoundingClientRect();
            score -= rect.top * 0.1;
            ranked.push({ btn, label, score });
        }
        ranked.sort((a, b) => b.score - a.score);
        if (ranked.length) {
            clickBtn(ranked[0].btn);
            return {
                clicked: true,
                text: ranked[0].label,
                method: 'ranked_new_promotion_button',
                className: ranked[0].btn.className || '',
            };
        }

        return { clicked: false, reason: 'new_promotion_button_not_found', url: location.href };
        """
    ) or {"clicked": False, "reason": "new_promotion_js_failed"}

    if result.get("clicked"):
        time.sleep(2)
        return result

    try:
        raw_page = getattr(page, "_page")
        for selector in (
            'button[class*="CreatePromotionBtn"]',
            'div[class*="GeneralV1_left"] button:has-text("新建推广")',
            'button.anq-btn-primary:has-text("新建推广")',
        ):
            btn = raw_page.locator(selector).first
            if btn.count():
                btn.click(timeout=5_000)
                time.sleep(2)
                return {"clicked": True, "text": "+ 新建推广", "method": f"playwright_{selector}"}
    except Exception as exc:
        print(f"[{account_id}] Playwright 点击新建推广失败: {_safe_exc(exc)}", flush=True)

    for label in ("+ 新建推广", "新建推广"):
        if _click_text(page, label, timeout=3):
            time.sleep(2)
            return {"clicked": True, "text": label, "method": "text_click"}

    return {
        "clicked": False,
        "reason": "new_promotion_button_not_found",
        "current_url": _page_url(page),
        "body_preview": _body_text(page)[:200],
    }


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
        if not _ensure_yingxiao_promotion_overview_url(page, account_id, account=account):
            return {
                "status": "failed",
                "step": "ensure_promotion_overview",
                "error": "已进入 yingxiao 但未加载到商品推广概况页",
                "current_url": _page_url(page),
                "open_tabs": [str(getattr(p, "url", "") or "") for p in _live_context_pages(page)],
                "selected_pdd_product_ids": selected_pdd_product_ids,
            }

        click_result = _click_new_promotion(page, account_id)
        if not click_result.get("clicked"):
            body_preview = _body_text(page)[:300]
            balance_hint = ""
            if "余额不足" in body_preview or "推广已中断" in body_preview:
                balance_hint = "；推广账户余额不足（需先充值）"
            return {
                "status": "failed",
                "step": "click_new_promotion",
                "error": (click_result.get("reason") or "未找到或无法点击新建推广") + balance_hint,
                "click_result": click_result,
                "current_url": _page_url(page),
                "open_tabs": [str(getattr(p, "url", "") or "") for p in _live_context_pages(page)],
                "body_preview": body_preview,
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

        edit_bid_result = _click_promotion_edit_bid_icons(
            page,
            account_id,
            selected_pdd_product_ids,
        )
        if edit_bid_result.get("status") != "success":
            return {
                "status": "failed",
                "step": edit_bid_result.get("step") or "click_edit_bid_icons",
                "error": edit_bid_result.get("error") or "点击推广设置小笔失败",
                "click_result": click_result,
                "drawer_wait": drawer_wait,
                "close_result": close_result,
                "search_result": search_result,
                "edit_bid_result": edit_bid_result,
                "current_url": _page_url(page),
                "selected_pdd_product_ids": selected_pdd_product_ids,
            }

        boost_checkbox_result = _ensure_global_boost_checkbox_unchecked(page, account_id)
        if boost_checkbox_result.get("status") != "success":
            return {
                "status": "failed",
                "step": boost_checkbox_result.get("step") or "ensure_global_boost_unchecked",
                "error": boost_checkbox_result.get("error") or "无法取消勾选全局优选起量",
                "click_result": click_result,
                "drawer_wait": drawer_wait,
                "close_result": close_result,
                "search_result": search_result,
                "edit_bid_result": edit_bid_result,
                "boost_checkbox_result": boost_checkbox_result,
                "current_url": _page_url(page),
                "selected_pdd_product_ids": selected_pdd_product_ids,
            }

        return {
            "status": "success",
            "step": "global_boost_unchecked",
            "message": (
                f"已为 {edit_bid_result.get('found_count', 0)} 个商品设置净目标投产比，"
                f"并已取消勾选全局优选起量"
            ),
            "click_result": click_result,
            "drawer_wait": drawer_wait,
            "close_result": close_result,
            "search_result": search_result,
            "edit_bid_result": edit_bid_result,
            "boost_checkbox_result": boost_checkbox_result,
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

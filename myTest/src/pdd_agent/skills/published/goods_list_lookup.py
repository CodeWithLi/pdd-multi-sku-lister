"""在拼多多商家后台商品列表中，按商品 ID 只读反查规格价格。

安全约束：仅搜索列表、打开 goods_detail 详情页、读取 DOM，绝不进入编辑页或修改商品。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.logging import get_logger
from pdd_agent.skills.listing.upload import (
    _click_goods_search,
    _fill_goods_id_filter,
    _open_goods_list,
    _reset_goods_list_filters,
)

from pdd_agent.skills.published.spec_inventory_scrape import scrape_spec_inventory

logger = get_logger(__name__)

_PARSE_ROW_JS = """
const productId = String(arguments[0] || '').trim();
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none'
        && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function rowMatches(row, id) {
    const text = (row.innerText || row.textContent || '').replace(/\\s+/g, ' ');
    return text.includes('ID: ' + id) || text.includes('ID:' + id) || text.includes(id);
}
function pickPrice(text) {
    const group = text.match(/拼单价[：:\\s]*([\\d.]+)/);
    if (group) return group[1];
    const plain = text.match(/(?:^|[\\s￥¥])([\\d]{1,4}(?:\\.\\d{1,2})?)(?=[\\s]|$)/);
    return plain ? plain[1] : '';
}
function pickActivityPrice(text) {
    const m = text.match(/活动价[：:\\s]*([\\d.]+)/);
    return m ? m[1] : '';
}
function pickInventory(text) {
    const m = text.match(/总库存[：:\\s]*([\\d,]+)/);
    if (m) return m[1].replace(/,/g, '');
    const m2 = text.match(/库存[：:\\s]*([\\d,]+)/);
    return m2 ? m2[1].replace(/,/g, '') : '';
}
const rows = Array.from(document.querySelectorAll('tbody tr, tr[class*="goods"], div[class*="goods-item"]'));
for (const row of rows) {
    if (!isVisible(row) || !rowMatches(row, productId)) continue;
    const nameEl = row.querySelector('span.goods-name, .goods-name, a.goods-name');
    const title = nameEl ? (nameEl.innerText || nameEl.textContent || '').trim() : '';
    const text = (row.innerText || row.textContent || '').replace(/\\s+/g, ' ');
    return {
        title,
        group_price: pickPrice(text),
        activity_price: pickActivityPrice(text),
        inventory: pickInventory(text),
        has_goods_name: Boolean(nameEl),
    };
}
return null;
"""

_CLICK_GOODS_NAME_JS = """
const productId = String(arguments[0] || '').trim();
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none'
        && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function rowMatches(row, id) {
    const text = (row.innerText || row.textContent || '').replace(/\\s+/g, ' ');
    return text.includes('ID: ' + id) || text.includes('ID:' + id) || text.includes(id);
}
function mouseClick(el) {
    el.scrollIntoView({ block: 'center', inline: 'center' });
    for (const type of ['mousedown', 'mouseup', 'click']) {
        el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
}
function absHref(href) {
    if (!href) return '';
    try { return new URL(href, window.location.href).href; } catch (e) { return href; }
}
function isDetailHref(href) {
    return href.includes('goods_detail') && !href.includes('goods_add') && !href.includes('type=edit');
}
const rows = Array.from(document.querySelectorAll('tbody tr, tr[class*="goods"], div[class*="goods-item"]'));
for (const row of rows) {
    if (!isVisible(row) || !rowMatches(row, productId)) continue;
    for (const a of row.querySelectorAll('a[href]')) {
        const href = absHref(a.getAttribute('href') || '');
        if (!href || !isVisible(a) || !isDetailHref(href)) continue;
        mouseClick(a);
        return { ok: true, method: 'detail_anchor', href };
    }
    const idEl = row.querySelector('[class*="blue_title"], span.goods-name span, span.goods-name');
    const nameEl = idEl || row.querySelector('span.goods-name, .goods-name, a.goods-name');
    if (!nameEl || !isVisible(nameEl)) continue;
    mouseClick(nameEl);
    return { ok: true, method: 'goods_name', href: '' };
}
return { ok: false, method: '', href: '' };
"""

_FIND_ROW_DETAIL_HREF_JS = """
const productId = String(arguments[0] || '').trim();
function absHref(href) {
    if (!href) return '';
    try { return new URL(href, window.location.href).href; } catch (e) { return href; }
}
function isDetailHref(href) {
    return href.includes('goods_detail') && !href.includes('goods_add') && !href.includes('type=edit');
}
function rowMatches(row, id) {
    const text = (row.innerText || row.textContent || '').replace(/\\s+/g, ' ');
    return text.includes('ID: ' + id) || text.includes('ID:' + id) || text.includes(id);
}
for (const row of document.querySelectorAll('tbody tr, tr[class*="goods"], div[class*="goods-item"]')) {
    if (!rowMatches(row, productId)) continue;
    for (const a of row.querySelectorAll('a[href]')) {
        const href = absHref(a.getAttribute('href') || '');
        if (href && isDetailHref(href)) return href;
    }
}
return '';
"""

GOODS_DETAIL_URLS = (
    "https://mms.pinduoduo.com/goods/goods_detail?goods_id={product_id}",
    "https://mms.pinduoduo.com/goods/goods_detail?id={product_id}",
)


def _parse_goods_list_row(page: DpPage, product_id: str) -> dict[str, Any] | None:
    try:
        row = page.run_js(_PARSE_ROW_JS, product_id)
        return row if isinstance(row, dict) else None
    except Exception:
        return None


def _wait_goods_list_row(page: DpPage, product_id: str, timeout: float = 15.0) -> dict[str, Any] | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = _parse_goods_list_row(page, product_id)
        if row:
            return row
        time.sleep(0.5)
    return None


def _detect_product_page(page: DpPage) -> str | None:
    url = str(page.url or "")
    if "goods_add" in url or "type=edit" in url or "/goods/edit" in url:
        return None
    if "goods_detail" in url or "goods/detail" in url or "/detail/" in url:
        return "detail"
    try:
        body = page.run_js("return (document.body && document.body.innerText) || ''") or ""
    except Exception:
        body = ""
    if "商品详情" in body or "规格与库存" in body:
        return "detail"
    return None


def _maybe_switch_new_tab(page: DpPage, tabs_before: int) -> DpPage | None:
    try:
        ctx = page._page.context
        pages = ctx.pages
        if len(pages) <= tabs_before:
            return None
        new_page = pages[-1]
        new_page.wait_for_load_state("domcontentloaded", timeout=15000)
        return DpPage(new_page)
    except Exception:
        return None


def _click_goods_row_playwright(page: DpPage, product_id: str) -> bool:
    rows = page.eles("css:tbody tr", timeout=3)
    for row in rows:
        text = row.text or ""
        if product_id not in text:
            continue
        for sel in ("css:a[href*='goods_detail']", "css:span.goods-name", "css:[class*='blue_title']"):
            el = row.ele(sel, timeout=0.4)
            if not el:
                continue
            try:
                el.click()
                return True
            except Exception:
                continue
    return False


def _open_goods_detail_direct(page: DpPage, product_id: str) -> bool:
    for template in GOODS_DETAIL_URLS:
        url = template.format(product_id=product_id)
        try:
            page.get(url)
            deadline = time.time() + 25
            while time.time() < deadline:
                if _detect_product_page(page):
                    return True
                time.sleep(0.6)
        except Exception:
            continue
    return False


def _navigate_to_goods_detail(page: DpPage, product_id: str) -> tuple[DpPage, str, str]:
    """只读：列表确认存在后，直接打开 goods_detail 详情页。"""
    if _open_goods_detail_direct(page, product_id):
        return page, "detail", "direct_detail_url"
    return page, "", "failed"


def _click_goods_name_by_id(page: DpPage, product_id: str) -> bool:
    active, kind, _method = _navigate_to_goods_detail(page, product_id)
    return bool(kind)


def lookup_published_product_in_goods_list(
    page: DpPage,
    account_id: str,
    pdd_product_id: str,
) -> dict[str, Any]:
    """打开商品列表 → 按商品 ID 查询 → 点击商品名称进入编辑页。"""
    product_id = str(pdd_product_id or "").strip()
    synced_at = datetime.now().isoformat(timespec="seconds")
    if not product_id:
        return {"status": "failed", "error": "pdd_product_id is required"}

    logger.info("[%s] goods list lookup start product_id=%s", account_id, product_id)

    if not _open_goods_list(page, account_id, tab_text="在售中"):
        return {"status": "failed", "error": "无法打开商品列表，可能未登录"}

    _reset_goods_list_filters(page)
    time.sleep(0.8)

    fill_result = _fill_goods_id_filter(page, product_id)
    if not fill_result.get("filled"):
        return {
            "status": "failed",
            "error": "无法填写商品ID搜索框",
            "search_steps": {"fill_result": fill_result},
        }

    time.sleep(0.3)
    click_result = _click_goods_search(page)
    if not click_result.get("clicked"):
        return {
            "status": "failed",
            "error": "无法点击查询按钮",
            "search_steps": {"fill_result": fill_result, "click_result": click_result},
        }

    logger.info(
        "[%s] goods list search product_id=%s fill=%s click=%s",
        account_id,
        product_id,
        fill_result.get("method"),
        click_result.get("method"),
    )

    list_row = _wait_goods_list_row(page, product_id)
    if not list_row:
        return {
            "status": "failed",
            "error": f"商品列表未找到商品 ID={product_id}",
            "pdd_goods_lookup": {
                "status": "search_failed",
                "synced_at": synced_at,
                "pdd_product_id": product_id,
                "search_steps": {"fill_result": fill_result, "click_result": click_result},
            },
        }

    if not list_row.get("has_goods_name"):
        return {
            "status": "failed",
            "error": f"找到商品但未定位到商品名称区域 ID={product_id}",
            "pdd_goods_lookup": {
                "status": "searched",
                "synced_at": synced_at,
                "pdd_product_id": product_id,
                "list_row": {k: v for k, v in list_row.items() if k != "has_goods_name"},
            },
        }

    active_page, page_kind, navigate_method = _navigate_to_goods_detail(page, product_id)
    clean_row = {k: v for k, v in list_row.items() if k != "has_goods_name"}

    lookup_payload: dict[str, Any] = {
        "status": "detail_opened" if page_kind else "searched",
        "synced_at": synced_at,
        "pdd_product_id": product_id,
        "list_row": clean_row,
        "detail_url": str(active_page.url or ""),
        "page_kind": page_kind or "",
        "navigate_method": navigate_method,
        "search_steps": {"fill_result": fill_result, "click_result": click_result},
    }

    if not page_kind:
        return {
            "status": "failed",
            "error": "未能进入只读商品详情页（goods_detail）",
            "pdd_product_id": product_id,
            "pdd_goods_lookup": lookup_payload,
        }

    spec_result = scrape_spec_inventory(active_page, pdd_product_id=product_id)
    pdd_skus = spec_result.get("skus") or []
    lookup_payload["pdd_skus"] = pdd_skus
    lookup_payload["sku_fields"] = spec_result.get("fields") or []
    lookup_payload["sku_count"] = len(pdd_skus)
    lookup_payload["scrape_source"] = spec_result.get("scrape_source") or ""
    lookup_payload["read_only"] = True
    lookup_payload["detail_url"] = str(spec_result.get("detail_url") or active_page.url or "")
    lookup_payload["scrape_debug"] = spec_result.get("scrape_debug") or {}
    lookup_payload["scrape_steps"] = spec_result.get("scrape_steps") or []
    lookup_payload["spec_dim1_key"] = spec_result.get("spec_dim1_key") or "款式"
    lookup_payload["spec_dim2_key"] = spec_result.get("spec_dim2_key") or "套餐"

    if pdd_skus:
        lookup_payload["status"] = "specs_synced"
        logger.info(
            "[%s] goods lookup synced product_id=%s sku_count=%s",
            account_id,
            product_id,
            len(pdd_skus),
        )
        return {
            "status": "success",
            "pdd_product_id": product_id,
            "pdd_goods_lookup": lookup_payload,
            "message": f"已反查 {len(pdd_skus)} 个 SKU 规格价格 ID={product_id}",
        }

    lookup_payload["status"] = "detail_opened"
    lookup_payload["scrape_error"] = spec_result.get("error") or "spec_rows_empty"
    debug = spec_result.get("scrape_debug") or {}
    summary = (
        f"section={debug.get('section_found')} table={debug.get('table_found')} "
        f"rows={debug.get('row_total')} parsed={debug.get('row_parsed')} "
        f"skipped_empty={debug.get('row_skipped_empty')}"
    )
    return {
        "status": "failed",
        "error": f"已进入商品页但未抓取到规格与库存数据 ID={product_id} ({summary})",
        "pdd_product_id": product_id,
        "pdd_goods_lookup": lookup_payload,
        "scrape_debug": debug,
        "scrape_steps": spec_result.get("scrape_steps") or [],
    }

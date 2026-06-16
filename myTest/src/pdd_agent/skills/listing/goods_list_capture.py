"""商品列表核验：解析行元数据、复制 C 端商品链接。"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.delist.time_utils import extract_created_at_from_text, format_datetime

_LIST_STATUS_CANDIDATES = (
    "销售中",
    "已驳回",
    "已下架",
    "审核中",
    "待审核",
    "草稿",
)

_CLICK_QR_LINK_JS = """
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
const rows = Array.from(document.querySelectorAll('tbody tr, tr[class*="goods"], div[class*="goods-item"]'));
for (const row of rows) {
    if (!isVisible(row) || !rowMatches(row, productId)) continue;
    const nodes = Array.from(row.querySelectorAll('a, span, div, button'));
    for (const el of nodes) {
        if (!isVisible(el)) continue;
        const text = (el.innerText || el.textContent || '').trim();
        if (!text) continue;
        if (text.includes('二维码/链接') || text.includes('二维码') && text.includes('链接')) {
            mouseClick(el);
            return { ok: true, method: 'qr_link_text' };
        }
        if (text === '链接' || text === '复制链接') {
            mouseClick(el);
            return { ok: true, method: 'link_text' };
        }
    }
}
return { ok: false, method: '' };
"""

_READ_MOBILE_LINK_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none'
        && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function pickUrl(text) {
    const raw = String(text || '').trim();
    if (!raw) return '';
    const m = raw.match(/https?:\\/\\/[^\\s"'<>]+/);
    if (!m) return '';
    const url = m[0];
    if (url.includes('yangkeduo.com') && url.includes('goods')) return url;
    return '';
}
for (const sel of ['input', 'textarea']) {
    for (const el of document.querySelectorAll(sel)) {
        if (!isVisible(el)) continue;
        const url = pickUrl(el.value || el.getAttribute('value') || '');
        if (url) return { link: url, method: 'input' };
    }
}
for (const el of document.querySelectorAll('div, span, p, a')) {
    if (!isVisible(el)) continue;
    const url = pickUrl(el.innerText || el.textContent || el.getAttribute('href') || '');
    if (url) return { link: url, method: 'text' };
}
return { link: '', method: '' };
"""

_CLICK_COPY_LINK_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none'
        && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function mouseClick(el) {
    el.scrollIntoView({ block: 'center', inline: 'center' });
    for (const type of ['mousedown', 'mouseup', 'click']) {
        el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
}
for (const el of document.querySelectorAll('button, a, span, div')) {
    if (!isVisible(el)) continue;
    const text = (el.innerText || el.textContent || '').trim();
    if (text === '复制链接' || text.includes('复制链接')) {
        mouseClick(el);
        return { ok: true };
    }
}
return { ok: false };
"""


def extract_list_status_from_text(text: str) -> str:
    if not text:
        return ""
    for status in _LIST_STATUS_CANDIDATES:
        if status in text:
            return status
    match = re.search(
        r"20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?\s*\n\s*(\S+)",
        text,
    )
    if match:
        return match.group(1).strip()
    return ""


def parse_goods_list_row_meta(row_text: str) -> dict[str, str]:
    created_dt = extract_created_at_from_text(row_text)
    return {
        "matched_created_at": format_datetime(created_dt) if created_dt else "",
        "list_status": extract_list_status_from_text(row_text),
    }


def _close_link_modal(page: DpPage) -> None:
    for selector in (
        "text:关闭",
        "text:取消",
        "css:.modal-close",
        "css:[class*='close']",
    ):
        try:
            el = page.ele(selector, timeout=0.4)
            if el:
                el.click()
                time.sleep(0.3)
                return
        except Exception:
            continue
    try:
        page.run_js(
            """
            for (const el of document.querySelectorAll('button, span, i, div')) {
                const text = (el.innerText || el.textContent || '').trim();
                if (text === '×' || text === '关闭') {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
    except Exception:
        pass


def copy_mobile_product_link(page: DpPage, product_id: str, *, fallback: str = "") -> dict[str, Any]:
    """点击「二维码/链接」弹窗并读取 C 端商品链接。"""
    product_id = str(product_id or "").strip()
    if not product_id:
        return {"link": fallback, "method": "empty_product_id", "ok": False}

    clicked: dict[str, Any] = {"ok": False}
    try:
        raw = page.run_js(_CLICK_QR_LINK_JS, product_id)
        clicked = raw if isinstance(raw, dict) else {"ok": bool(raw)}
    except Exception:
        clicked = {"ok": False}

    if not clicked.get("ok"):
        for row in page.eles("css:tbody tr", timeout=2) or []:
            text = row.text or ""
            if product_id not in text:
                continue
            try:
                link_el = row.ele("text:二维码/链接", timeout=0.5) or row.ele("text:链接", timeout=0.3)
                if link_el:
                    link_el.click()
                    clicked = {"ok": True, "method": "dp_ele"}
                    break
            except Exception:
                continue

    if not clicked.get("ok"):
        return {"link": fallback, "method": "click_failed", "ok": False}

    deadline = time.time() + 8.0
    link = ""
    method = ""
    while time.time() < deadline and not link:
        try:
            raw = page.run_js(_READ_MOBILE_LINK_JS)
            if isinstance(raw, dict):
                link = str(raw.get("link") or "").strip()
                method = str(raw.get("method") or "")
        except Exception:
            pass
        if link:
            break
        try:
            page.run_js(_CLICK_COPY_LINK_JS)
        except Exception:
            pass
        time.sleep(0.4)

    _close_link_modal(page)

    if not link:
        link = fallback
        method = "fallback_template" if fallback else "not_found"
    return {"link": link, "method": method or str(clicked.get("method") or ""), "ok": bool(link)}


def enrich_capture_from_goods_list(
    page: DpPage,
    capture: dict[str, Any],
    *,
    merchant_code: str,
    title: str,
    fallback_link: str = "",
) -> dict[str, Any]:
    """在核验成功后补全创建时间、状态、C 端链接。"""
    row_text = str(capture.get("matched_row_text") or "")
    if not row_text:
        matches = []
        try:
            rows = page.eles("css:tbody tr", timeout=2) or []
        except Exception:
            rows = []
        product_id = str(capture.get("pdd_product_id") or "")
        for row in rows:
            text = row.text or ""
            if product_id and product_id not in text:
                continue
            if merchant_code and merchant_code not in text:
                continue
            row_text = text.strip()
            break

    meta = parse_goods_list_row_meta(row_text)
    if meta.get("matched_created_at"):
        capture["matched_created_at"] = meta["matched_created_at"]
    if meta.get("list_status"):
        capture["list_status"] = meta["list_status"]

    product_id = str(capture.get("pdd_product_id") or "")
    link_result = copy_mobile_product_link(page, product_id, fallback=fallback_link)
    capture["product_link"] = link_result.get("link") or fallback_link
    capture["product_link_method"] = link_result.get("method") or ""
    if title:
        capture["matched_title"] = title
    return capture

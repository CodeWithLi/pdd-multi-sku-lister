"""商品列表核验：解析行元数据、复制 C 端商品链接。"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

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

_QR_LINK_LABELS = (
    "分享/二维码",
    "二维码链接",
    "二维码/链接",
)

_READ_MODAL_LINK_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none'
        && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function pickGoodsUrls(text) {
    const raw = String(text || '');
    const matches = raw.match(/https?:\\/\\/mobile\\.yangkeduo\\.com\\/goods\\.html[^\\s"'<>]*/g) || [];
    const uniq = Array.from(new Set(matches.map((u) => u.trim())));
    uniq.sort((a, b) => b.length - a.length);
    return uniq;
}
function readFromModal() {
    const roots = Array.from(document.querySelectorAll(
        '[role="dialog"], [class*="modal"], [class*="Modal"], [class*="drawer"], body'
    ));
    for (const root of roots) {
        if (!isVisible(root)) continue;
        const text = root.innerText || root.textContent || '';
        if (!text.includes('商品链接') && !text.includes('商品二维码')) continue;
        const urls = pickGoodsUrls(text);
        if (urls.length) {
            return { link: urls[0], method: 'modal_text', count: urls.length };
        }
        for (const el of root.querySelectorAll('input, textarea')) {
            if (!isVisible(el)) continue;
            const urls2 = pickGoodsUrls(el.value || el.getAttribute('value') || '');
            if (urls2.length) return { link: urls2[0], method: 'modal_input', count: urls2.length };
        }
    }
    const all = pickGoodsUrls(document.body ? document.body.innerText : '');
    if (all.length) return { link: all[0], method: 'body_text', count: all.length };
    return { link: '', method: '', count: 0 };
}
return readFromModal();
"""


def is_plain_goods_template_link(link: str, product_id: str) -> bool:
    """判断是否为无 refer 参数的模板短链（用户不要这种）。"""
    url = str(link or "").strip()
    pid = str(product_id or "").strip()
    if not url or not pid:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if "yangkeduo.com" not in parsed.netloc or "goods.html" not in parsed.path:
        return False
    qs = parse_qs(parsed.query)
    goods_ids = qs.get("goods_id") or []
    if not goods_ids or str(goods_ids[0]) != pid:
        return False
    # 弹窗复制链接通常带 refer_page_* 等参数
    extra_keys = [k for k in qs if k != "goods_id"]
    return len(extra_keys) == 0


def _normalize_goods_link(link: str) -> str:
    return str(link or "").strip().rstrip(".,;)")


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


def extract_merchant_code_from_row_text(text: str) -> str:
    """从商品列表行文本提取商品编码/商家编码。"""
    if not text:
        return ""
    for pattern in (
        r"商品编码[：:\s]*([^\s\n]+)",
        r"商家编码[：:\s]*([^\s\n]+)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def extract_total_inventory_from_row_text(text: str) -> int | None:
    """从商品列表行文本提取总库存（整数）。"""
    if not text:
        return None
    match = re.search(r"总库存[：:\s]*([\d,]+)", text)
    if match:
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def parse_goods_list_row_meta(row_text: str) -> dict[str, str]:
    created_dt = extract_created_at_from_text(row_text)
    inventory = extract_total_inventory_from_row_text(row_text)
    return {
        "matched_created_at": format_datetime(created_dt) if created_dt else "",
        "list_status": extract_list_status_from_text(row_text),
        "merchant_code": extract_merchant_code_from_row_text(row_text),
        "total_inventory": str(inventory) if inventory is not None else "",
    }


def _is_qr_link_label(text: str) -> bool:
    raw = re.sub(r"\s+", "", str(text or ""))
    if not raw:
        return False
    for label in _QR_LINK_LABELS:
        if label.replace(" ", "") in raw:
            return True
    return "二维码" in raw and ("链接" in raw or "分享" in raw)


def _click_share_qr_link_playwright(page: DpPage, product_id: str) -> dict[str, Any]:
    try:
        raw = page._page
        rows = raw.locator("tbody tr")
        row_count = rows.count()
    except Exception:
        return {"ok": False, "method": "playwright_unavailable"}

    for index in range(row_count):
        row = rows.nth(index)
        try:
            text = row.inner_text(timeout=1500) or ""
        except Exception:
            continue
        if product_id not in text:
            continue

        for label in _QR_LINK_LABELS:
            try:
                loc = row.get_by_text(label, exact=True)
                if loc.count() > 0:
                    loc.first.scroll_into_view_if_needed(timeout=2000)
                    loc.first.click(timeout=3000)
                    return {"ok": True, "method": f"playwright_text_{label}"}
            except Exception:
                continue

        try:
            links = row.locator("a[data-testid='beast-core-button-link']")
            for link_index in range(links.count()):
                link_el = links.nth(link_index)
                label_text = (link_el.inner_text(timeout=500) or "").strip()
                if not _is_qr_link_label(label_text):
                    continue
                link_el.scroll_into_view_if_needed(timeout=2000)
                link_el.click(timeout=3000)
                return {"ok": True, "method": f"playwright_beast_link_{label_text}"}
        except Exception:
            continue

    return {"ok": False, "method": "playwright_row_not_found"}


def _click_share_qr_link_js(page: DpPage, product_id: str) -> dict[str, Any]:
    js = """
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
    function isQrLabel(text) {
        const t = String(text || '').replace(/\\s+/g, '');
        return t.includes('分享/二维码') || t.includes('二维码链接') || t.includes('二维码/链接')
            || (t.includes('二维码') && (t.includes('链接') || t.includes('分享')));
    }
    function mouseClick(el) {
        const target = el.closest('a,button') || el;
        target.scrollIntoView({ block: 'center', inline: 'center' });
        for (const type of ['mousedown', 'mouseup', 'click']) {
            target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
        }
    }
    const rows = Array.from(document.querySelectorAll('tbody tr, tr[class*="goods"], div[class*="goods-item"]'));
    for (const row of rows) {
        if (!isVisible(row) || !rowMatches(row, productId)) continue;
        for (const el of row.querySelectorAll('a, span, div, button')) {
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').trim();
            if (!isQrLabel(text)) continue;
            mouseClick(el);
            return { ok: true, method: 'js_qr_label', label: text };
        }
    }
    return { ok: false, method: '' };
    """
    try:
        raw = page.run_js(js, product_id)
        return raw if isinstance(raw, dict) else {"ok": bool(raw)}
    except Exception:
        return {"ok": False, "method": "js_click_failed"}


def _wait_qr_modal(page: DpPage, timeout: float = 6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if page.ele("text:商品链接", timeout=0.4) or page.ele("text:商品二维码", timeout=0.4):
                return True
        except Exception:
            pass
        try:
            raw = page._page.get_by_text("商品链接").first
            if raw.is_visible(timeout=400):
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def _read_link_from_modal(page: DpPage) -> dict[str, Any]:
    try:
        raw = page.run_js(_READ_MODAL_LINK_JS)
        if isinstance(raw, dict):
            link = _normalize_goods_link(str(raw.get("link") or ""))
            if link:
                return {"link": link, "method": str(raw.get("method") or "modal")}
    except Exception:
        pass
    return {"link": "", "method": ""}


def _click_copy_link(page: DpPage) -> bool:
    for label in ("复制链接",):
        try:
            el = page.ele(f"text:{label}", timeout=0.5)
            if el:
                el.click()
                return True
        except Exception:
            continue
    try:
        raw = page._page.get_by_role("button", name="复制链接")
        if raw.count() > 0:
            raw.first.click(timeout=2000)
            return True
    except Exception:
        pass
    try:
        raw = page._page.get_by_text("复制链接", exact=True)
        if raw.count() > 0:
            raw.first.click(timeout=2000)
            return True
    except Exception:
        pass
    return False


def _read_clipboard_link(page: DpPage) -> str:
    try:
        text = page._page.evaluate(
            """async () => {
                try {
                    return await navigator.clipboard.readText();
                } catch (e) {
                    return '';
                }
            }"""
        )
        link = _normalize_goods_link(str(text or ""))
        if "yangkeduo.com" in link and "goods.html" in link:
            return link
    except Exception:
        pass
    return ""


def _close_link_modal(page: DpPage) -> None:
    for selector in ("text:关闭", "text:取消", "css:.modal-close", "css:[class*='close']"):
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
    """点击「分享/二维码」弹窗并读取完整 C 端商品链接（带 refer 参数）。"""
    product_id = str(product_id or "").strip()
    if not product_id:
        return {"link": "", "method": "empty_product_id", "ok": False}

    clicked = _click_share_qr_link_playwright(page, product_id)
    if not clicked.get("ok"):
        clicked = _click_share_qr_link_js(page, product_id)

    if not clicked.get("ok"):
        for row in page.eles("css:tbody tr", timeout=2) or []:
            text = row.text or ""
            if product_id not in text:
                continue
            for label in _QR_LINK_LABELS:
                try:
                    link_el = row.ele(f"text:{label}", timeout=0.4)
                    if link_el:
                        link_el.click()
                        clicked = {"ok": True, "method": f"dp_ele_{label}"}
                        break
                except Exception:
                    continue
            if clicked.get("ok"):
                break

    if not clicked.get("ok"):
        return {"link": "", "method": "click_failed", "ok": False}

    _wait_qr_modal(page, timeout=6.0)

    link = ""
    method = ""
    deadline = time.time() + 8.0
    while time.time() < deadline and not link:
        result = _read_link_from_modal(page)
        candidate = _normalize_goods_link(str(result.get("link") or ""))
        if candidate and not is_plain_goods_template_link(candidate, product_id):
            link = candidate
            method = str(result.get("method") or "modal")
            break
        if _click_copy_link(page):
            time.sleep(0.35)
            clip = _read_clipboard_link(page)
            if clip and not is_plain_goods_template_link(clip, product_id):
                link = clip
                method = "clipboard"
                break
        time.sleep(0.35)

    _close_link_modal(page)

    if link and not is_plain_goods_template_link(link, product_id):
        return {"link": link, "method": method or str(clicked.get("method") or ""), "ok": True}

    # 不接受无 refer 的模板短链
    if fallback and not is_plain_goods_template_link(fallback, product_id):
        return {"link": fallback, "method": "fallback_non_template", "ok": True}

    return {
        "link": "",
        "method": method or str(clicked.get("method") or "modal_empty"),
        "ok": False,
    }


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
    link = str(link_result.get("link") or "").strip()
    capture["product_link"] = link
    capture["product_link_method"] = link_result.get("method") or ""
    capture["product_link_ok"] = bool(link_result.get("ok"))
    if title:
        capture["matched_title"] = title
    return capture

"""抖店商品管理：按商家编码查询并抓取 ID / 状态 / 上架时间 / 复制链接。"""

from __future__ import annotations

import re
import time
from typing import Any

from playwright.sync_api import Page

from dy_agent.skills.listing.publish_navigate import GOODS_LIST_URL

_LIST_STATUS_CANDIDATES = (
    "售卖中",
    "已下架",
    "已封禁",
    "审核中",
    "审核驳回",
    "草稿",
    "已售罄",
)

_PRODUCT_ID_RE = re.compile(r"ID[：:\s]*(\d{10,})")
_LIST_TIME_RE = re.compile(
    r"(20\d{2}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)"
)


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def extract_product_id_from_text(text: str) -> str:
    if not text:
        return ""
    match = _PRODUCT_ID_RE.search(text)
    return match.group(1).strip() if match else ""


def extract_list_time_from_text(text: str) -> str:
    if not text:
        return ""
    match = _LIST_TIME_RE.search(text)
    return match.group(1).strip() if match else ""


def extract_list_status_from_text(text: str) -> str:
    if not text:
        return ""
    for status in _LIST_STATUS_CANDIDATES:
        if status in text:
            return status
    return ""


def _goods_list_ui_ready(page: Page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return False
    return "商品管理" in text and ("查询" in text or "售卖中" in text)


def _wait_goods_list_ui_ready(page: Page, *, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _goods_list_ui_ready(page):
            return True
        time.sleep(0.5)
    return _goods_list_ui_ready(page)


def _refresh_goods_list_page(page: Page, account_id: str, label: str) -> None:
    _log(account_id, label, "刷新商品管理页…")
    try:
        page.reload(wait_until="domcontentloaded", timeout=30_000)
    except Exception:
        page.goto(GOODS_LIST_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    _wait_goods_list_ui_ready(page, timeout=15.0)
    time.sleep(1.0)


def _ensure_goods_list_page(page: Page, account_id: str, label: str) -> None:
    if _goods_list_ui_ready(page):
        return
    _log(account_id, label, f"打开商品管理页: {GOODS_LIST_URL}")
    page.goto(GOODS_LIST_URL, wait_until="domcontentloaded")
    _wait_goods_list_ui_ready(page, timeout=20.0)
    time.sleep(1.5)


def _click_tab_if_present(page: Page, tab_text: str) -> bool:
    try:
        tab = page.locator("[role='tab']").filter(has_text=tab_text)
        if tab.count() > 0:
            tab.first.click(timeout=5_000)
            time.sleep(1)
            return True
    except Exception:
        pass
    try:
        tab = page.get_by_text(tab_text, exact=True)
        if tab.count() > 0:
            tab.first.click(timeout=5_000)
            time.sleep(1)
            return True
    except Exception:
        pass
    return False


def _fill_search_query(page: Page, query: str) -> bool:
    query = str(query or "").strip()
    if not query:
        return False
    selectors = [
        'input[placeholder*="商家编码"]',
        'input[placeholder*="商品名称"]',
        'input[placeholder*="商品ID"]',
    ]
    for selector in selectors:
        loc = page.locator(selector)
        if loc.count() == 0:
            continue
        try:
            inp = loc.first
            inp.scroll_into_view_if_needed(timeout=5_000)
            inp.click(timeout=3_000)
            inp.fill("", timeout=3_000)
            inp.fill(query, timeout=3_000)
            time.sleep(0.2)
            current = inp.input_value(timeout=2_000)
            if query in str(current or ""):
                return True
        except Exception:
            continue

    filled = page.evaluate(
        """
        (query) => {
          function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
          }
          const inputs = Array.from(document.querySelectorAll('input'));
          for (const inp of inputs) {
            const ph = inp.placeholder || '';
            if (!visible(inp)) continue;
            if (!ph.includes('商家编码') && !ph.includes('商品名称') && !ph.includes('商品ID')) continue;
            inp.focus();
            inp.value = '';
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.value = query;
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            return inp.value.includes(query);
          }
          return false;
        }
        """,
        query,
    )
    return bool(filled)


def _click_search_button(page: Page) -> bool:
    for label in ("查询",):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0:
                btn.first.scroll_into_view_if_needed(timeout=5_000)
                btn.first.click(timeout=5_000)
                time.sleep(1.5)
                return True
        except Exception:
            pass
        try:
            btn = page.locator("button").filter(has_text=label)
            if btn.count() > 0:
                btn.first.scroll_into_view_if_needed(timeout=5_000)
                btn.first.click(timeout=5_000)
                time.sleep(1.5)
                return True
        except Exception:
            pass
    return False


def _parse_goods_rows(page: Page) -> list[dict[str, str]]:
    rows = page.evaluate(
        """
        () => {
          function norm(text) {
            return String(text || '').replace(/\\s+/g, ' ').trim();
          }
          const out = [];
          const trs = document.querySelectorAll('tbody tr, tr[class*="row"], tr');
          for (const tr of trs) {
            const text = norm(tr.innerText || tr.textContent || '');
            if (!text || text.length < 8) continue;
            if (!text.includes('ID') && !/\\d{10,}/.test(text)) continue;
            out.push({ row_text: text });
          }
          return out;
        }
        """
    )
    parsed: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return parsed
    for item in rows:
        if not isinstance(item, dict):
            continue
        text = str(item.get("row_text") or "")
        product_id = extract_product_id_from_text(text)
        if not product_id:
            continue
        parsed.append(
            {
                "row_text": text,
                "dy_product_id": product_id,
                "list_status": extract_list_status_from_text(text),
                "listed_at": extract_list_time_from_text(text),
            }
        )
    return parsed


def _row_matches_query(row_text: str, query: str) -> bool:
    query = str(query or "").strip()
    if not query:
        return True
    return query in row_text


def _read_clipboard_link(page: Page) -> str:
    try:
        text = page.evaluate(
            """async () => {
                try { return await navigator.clipboard.readText(); }
                catch (e) { return ''; }
            }"""
        )
        link = str(text or "").strip()
        if link.startswith("http"):
            return link
    except Exception:
        pass
    return ""


def _copy_link_for_product(page: Page, product_id: str) -> dict[str, Any]:
    product_id = str(product_id or "").strip()
    if not product_id:
        return {"ok": False, "method": "empty_product_id", "link": ""}

    clicked = page.evaluate(
        """
        (productId) => {
          function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
          }
          function clickEl(el) {
            el.scrollIntoView({ block: 'center', inline: 'center' });
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
          }
          const rows = Array.from(document.querySelectorAll('tbody tr, tr'));
          for (const tr of rows) {
            const text = tr.innerText || tr.textContent || '';
            if (!text.includes(productId)) continue;
            for (const el of tr.querySelectorAll('span, a, button, div')) {
              if (!visible(el)) continue;
              const t = (el.innerText || el.textContent || '').trim();
              if (t !== '复制链接') continue;
              clickEl(el);
              return { ok: true, method: 'js_copy_link' };
            }
          }
          return { ok: false, method: '' };
        }
        """,
        product_id,
    )
    if not isinstance(clicked, dict) or not clicked.get("ok"):
        try:
            row = page.locator("tbody tr").filter(has_text=product_id).first
            link = row.get_by_text("复制链接", exact=True)
            link.scroll_into_view_if_needed(timeout=5_000)
            link.click(timeout=5_000)
            clicked = {"ok": True, "method": "playwright_copy_link"}
        except Exception:
            clicked = {"ok": False, "method": "click_failed"}

    if not clicked.get("ok"):
        return {"ok": False, "method": str(clicked.get("method") or "click_failed"), "link": ""}

    time.sleep(0.6)
    link = _read_clipboard_link(page)
    toast_ok = False
    try:
        body = page.locator("body").inner_text(timeout=2_000)
        toast_ok = "商品链接已复制" in body
    except Exception:
        pass

    return {
        "ok": bool(link) or toast_ok,
        "method": str(clicked.get("method") or ""),
        "link": link,
        "toast_ok": toast_ok,
    }


def _search_once_for_merchant_code(
    page: Page,
    query: str,
    *,
    tab_text: str,
) -> tuple[list[dict[str, str]], str]:
    """返回 (匹配行, 错误码)；错误码为空表示已发起查询（可能 0 行）。"""
    _click_tab_if_present(page, tab_text)
    if not _fill_search_query(page, query):
        return [], "search_input_failed"
    if not _click_search_button(page):
        return [], "search_click_failed"
    time.sleep(1.5)
    rows = _parse_goods_rows(page)
    matches = [row for row in rows if _row_matches_query(row.get("row_text") or "", query)]
    if not matches and rows:
        # 刚发布商品常仅展示标题/ID，搜索结果通常只剩一行
        matches = rows[:1]
    return matches, ""


def capture_goods_by_merchant_code(
    page: Page,
    account_id: str,
    label: str,
    merchant_code: str,
    *,
    tab_text: str = "售卖中",
    max_attempts: int = 3,
) -> dict[str, Any]:
    """在商品管理页按商家编码查询，抓取 ID / 状态 / 上架时间，并复制链接。

    刚从发布成功页返回时列表常未刷出新商品，默认刷新并重试若干次。
    """
    query = str(merchant_code or "").strip()
    if not query:
        return {"status": "empty_query", "message": "商家编码为空"}

    attempts = max(1, int(max_attempts))
    last_error = ""

    for attempt in range(1, attempts + 1):
        _ensure_goods_list_page(page, account_id, label)
        if attempt == 1:
            _refresh_goods_list_page(page, account_id, label)
        else:
            _log(account_id, label, f"第 {attempt}/{attempts} 次重试：刷新后再次查询 {query}")
            _refresh_goods_list_page(page, account_id, label)
            time.sleep(2.0)

        matches, search_error = _search_once_for_merchant_code(
            page, query, tab_text=tab_text
        )
        if search_error == "search_input_failed":
            last_error = "未找到商品搜索框"
            _log(account_id, label, f"{last_error}（第 {attempt}/{attempts} 次）")
            continue
        if search_error == "search_click_failed":
            last_error = "未找到「查询」按钮"
            _log(account_id, label, f"{last_error}（第 {attempt}/{attempts} 次）")
            continue

        if matches:
            selected = matches[0]
            product_id = str(selected.get("dy_product_id") or "")
            list_status = str(selected.get("list_status") or "")
            listed_at = str(selected.get("listed_at") or "")

            link_result = _copy_link_for_product(page, product_id)
            product_link = str(link_result.get("link") or "")

            _log(
                account_id,
                label,
                f"商品列表抓取 ID={product_id} 状态={list_status or '-'} "
                f"上架时间={listed_at or '-'} 链接={'有' if product_link else '无'}"
                f"（第 {attempt} 次）",
            )

            return {
                "status": "captured",
                "merchant_code": query,
                "dy_product_id": product_id,
                "list_status": list_status,
                "listed_at": listed_at,
                "product_link": product_link,
                "product_link_ok": bool(product_link),
                "product_link_method": str(link_result.get("method") or ""),
                "matched_row_text": str(selected.get("row_text") or "")[:500],
                "attempt": attempt,
            }

        last_error = f"商品管理未查到编码 {query}"
        _log(account_id, label, f"{last_error}（第 {attempt}/{attempts} 次）")

    if last_error == "未找到商品搜索框":
        return {"status": "search_input_failed", "message": last_error, "attempts": attempts}
    if last_error == "未找到「查询」按钮":
        return {"status": "search_click_failed", "message": last_error, "attempts": attempts}

    _log(account_id, label, f"商品管理未查到编码 {query}")
    return {
        "status": "not_found",
        "merchant_code": query,
        "message": f"商品管理未查到编码 {query}",
        "attempts": attempts,
    }

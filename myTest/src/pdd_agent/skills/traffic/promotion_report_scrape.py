"""推广平台：推广概况 → 查看全部推广 → 稳定成本推广 → 昨日数据抓取。"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.config import AccountConfig
from pdd_agent.skills.campaign.limited_time import (
    _bind_page,
    _body_text,
    _click_text,
    _dismiss_message_popup,
    _live_context_pages,
    _safe_exc,
    _switch_to_latest_tab,
)
from pdd_agent.integrations.feishu.traffic_metric_columns import (
    is_known_metric_header,
    normalize_traffic_header,
    normalize_traffic_metrics,
)
from pdd_agent.skills.delist.automation import _go_next_page, _read_pagination_summary
from pdd_agent.skills.traffic.promotion_create import (
    _close_mms_tabs_when_yingxiao_ready,
    _ensure_session,
    _open_promotion_overview,
    _page_url,
)
from pdd_agent.browser.sync_login import is_login_url

MAX_PAGES = 200
PROMOTION_LIST_URL = "https://yingxiao.pinduoduo.com/goods/promotion/list"

PRODUCT_ID_PATTERN = re.compile(r"商品\s*ID[：:]\s*(\d{6,})", re.IGNORECASE)

_SCROLL_MARK_ATTR = "data-pdd-traffic-scroll"

_PREPARE_PROMOTION_TABLE_JS = f"""
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
    return String(text || '').replace(/\\s+/g, ' ').trim();
}}
function findScrollHeaderCells(root) {{
    const sorterCells = Array.from(root.querySelectorAll(
        '.anq-table-content .anq-table-header .anq-table-cell.column-with-sorter, '
        + '.anq-table-header:not(.anq-table-fixed-left *) .anq-table-cell.column-with-sorter, '
        + '.anq-table-body thead .anq-table-cell.column-with-sorter, '
        + '.ant-table-header .ant-table-cell.column-with-sorter'
    ));
    if (sorterCells.length >= 3) return sorterCells;
    const selectors = [
        '.anq-table-content > .anq-table-header .anq-table-thead .anq-table-cell',
        '.anq-table-content .anq-table-header .anq-table-cell',
        '.anq-table-header:not(.anq-table-fixed-left .anq-table-header) .anq-table-thead .anq-table-cell',
        '.ant-table-content > .ant-table-header .ant-table-cell',
        '.anq-table-body table thead .anq-table-cell',
        '.ant-table-body table thead .ant-table-cell',
    ];
    for (const sel of selectors) {{
        const cells = Array.from(root.querySelectorAll(sel));
        if (cells.length >= 3) return cells;
    }}
    return [];
}}
function extractScrollMetricHeaders(root) {{
    const headers = [];
    const seen = new Set();
    for (const cell of findScrollHeaderCells(root)) {{
        const text = norm(cell.innerText || cell.textContent || '');
        if (!text || seen.has(text)) continue;
        seen.add(text);
        headers.push(text);
    }}
    return headers;
}}
function syncTableScroll(root, scrollEl, pos) {{
    if (scrollEl) scrollEl.scrollLeft = pos;
    if (!root) return;
    for (const sel of [
        '.anq-table-header',
        '.anq-table-sticky-scroll',
        '.ant-table-header',
        '.ant-table-sticky-scroll',
        '[class*="sticky-scroll"]',
    ]) {{
        for (const node of Array.from(root.querySelectorAll(sel))) {{
            if (!node || node === scrollEl) continue;
            try {{ node.scrollLeft = pos; }} catch (e) {{}}
        }}
    }}
}}
function findListTableRoot() {{
    const picker = document.querySelector('[class*="ListDatePicker"]');
    if (picker) {{
        let node = picker.parentElement;
        for (let i = 0; i < 12 && node; i++) {{
            const table = node.querySelector('.anq-table-wrapper, .anq-table, .ant-table-wrapper, .ant-table');
            if (table && isVisible(table)) return table;
            node = node.parentElement;
        }}
    }}
    const tbody = document.querySelector('.anq-table-tbody, .ant-table-tbody');
    if (tbody && isVisible(tbody)) {{
        return tbody.closest('.anq-table-wrapper, .anq-table, .ant-table-wrapper, .ant-table, table') || tbody;
    }}
    return null;
}}
function findFixedTbody(root) {{
    const fixed = root.querySelector(
        '.anq-table-fixed-left .anq-table-tbody, .anq-table-ping-left .anq-table-tbody, '
        + '.ant-table-fixed-left .ant-table-tbody'
    );
    if (fixed && isVisible(fixed)) return fixed;
    const tbodies = Array.from(root.querySelectorAll('.anq-table-tbody, .ant-table-tbody, tbody'));
    for (const tb of tbodies) {{
        if (!isVisible(tb)) continue;
        if (/商品\\s*ID/i.test(tb.innerText || '')) return tb;
    }}
    return root.querySelector('.anq-table-tbody, .ant-table-tbody, tbody');
}}
function findScrollContainer(root) {{
    const selectors = [
        '.anq-table-body',
        '.anq-table-content',
        '.ant-table-body',
        '.ant-table-content',
        '[class*="table-content"]',
        '[class*="TableContent"]',
    ];
    let best = null;
    let bestOverflow = 0;
    for (const sel of selectors) {{
        for (const el of Array.from(root.querySelectorAll(sel))) {{
            if (!isVisible(el)) continue;
            if (el.closest('.anq-table-fixed-left, .anq-table-ping-left, .ant-table-fixed-left')) continue;
            const overflow = el.scrollWidth - el.clientWidth;
            if (overflow > bestOverflow) {{
                bestOverflow = overflow;
                best = el;
            }}
        }}
    }}
    if (best) return best;
    return root.querySelector('.anq-table-body, .anq-table-content, .ant-table-body') || root;
}}
function clearScrollMark() {{
    document.querySelectorAll('[{_SCROLL_MARK_ATTR}]').forEach((el) => {{
        el.removeAttribute('{_SCROLL_MARK_ATTR}');
    }});
}}
const root = findListTableRoot();
if (!root) {{
    clearScrollMark();
    return {{ ready: false, reason: 'table_not_found' }};
}}
const scrollEl = findScrollContainer(root);
const fixedTbody = findFixedTbody(root);
scrollEl.setAttribute('{_SCROLL_MARK_ATTR}', '1');
syncTableScroll(root, scrollEl, 0);
const maxScroll = Math.max(0, scrollEl.scrollWidth - scrollEl.clientWidth);
const scrollStep = Math.max(200, Math.floor(scrollEl.clientWidth * 0.55));
return {{
    ready: true,
    reason: 'ok',
    max_scroll: maxScroll,
    scroll_step: scrollStep,
    has_fixed_split: !!(fixedTbody && fixedTbody !== scrollEl.querySelector('.anq-table-tbody, .ant-table-tbody, tbody')),
}};
"""

_EXTRACT_PROMOTION_TABLE_SLICE_JS = f"""
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
    return String(text || '').replace(/\\s+/g, ' ').trim();
}}
function isCellValue(v) {{
    const s = String(v == null ? '' : v).trim();
    if (!s || s === '-') return false;
    if (!/^-?\\d+(?:\\.\\d+)?%?$/.test(s)) return false;
    const junk = ['详情', '数据', '更多', '手动暂停', '去开启', '预算日限额', '净目标投产比', '拼单价', '商品 ID', '商品ID'];
    for (const m of junk) {{
        if (s.includes(m)) return false;
    }}
    return true;
}}
function isMetricHeaderText(text) {{
    const t = norm(text);
    if (!t || t === '操作') return false;
    if (t.includes('推广状态') || t.includes('预算及出价') || t.includes('预算日限额')) return false;
    if (t.includes('推广/分组') || t === '推广' || t.startsWith('推广添加')) return false;
    if (t.includes('详情') || t.includes('操作')) return false;
    return true;
}}
function getSorterCellNodes(row) {{
    if (!row) return [];
    let cells = Array.from(row.querySelectorAll(
        ':scope > td.anq-table-cell.column-with-sorter, :scope > .anq-table-cell.column-with-sorter, '
        + ':scope > td.column-with-sorter'
    ));
    if (!cells.length) {{
        cells = Array.from(row.querySelectorAll('td.anq-table-cell.column-with-sorter, .anq-table-cell.column-with-sorter'));
    }}
    return cells;
}}
function isInScrollViewport(node, scrollContainer) {{
    if (!node || !scrollContainer) return false;
    const rect = node.getBoundingClientRect();
    const containerRect = scrollContainer.getBoundingClientRect();
    return rect.right > containerRect.left + 2 && rect.left < containerRect.right - 2;
}}
function findScrollHeaderCells(root) {{
    const sorterCells = Array.from(root.querySelectorAll(
        '.anq-table-content .anq-table-header .anq-table-cell.column-with-sorter, '
        + '.anq-table-header:not(.anq-table-fixed-left *) .anq-table-cell.column-with-sorter, '
        + '.anq-table-body thead .anq-table-cell.column-with-sorter, '
        + '.ant-table-header .ant-table-cell.column-with-sorter'
    ));
    if (sorterCells.length >= 3) {{
        return sorterCells.filter((cell) => isMetricHeaderText(norm(cell.innerText || cell.textContent || '')));
    }}
    const selectors = [
        '.anq-table-content > .anq-table-header .anq-table-thead .anq-table-cell',
        '.anq-table-content .anq-table-header .anq-table-cell',
        '.anq-table-body table thead .anq-table-cell',
    ];
    for (const sel of selectors) {{
        const cells = Array.from(root.querySelectorAll(sel))
            .filter((cell) => isMetricHeaderText(norm(cell.innerText || cell.textContent || '')));
        if (cells.length >= 3) return cells;
    }}
    return [];
}}
function extractScrollMetricHeaders(root) {{
    const headers = [];
    const seen = new Set();
    for (const cell of findScrollHeaderCells(root)) {{
        const text = norm(cell.innerText || cell.textContent || '');
        if (!text || seen.has(text) || !isMetricHeaderText(text)) continue;
        seen.add(text);
        headers.push(text);
    }}
    return headers;
}}
function mapCellsToHeaders(cells, headers) {{
    const out = {{}};
    const n = Math.min(headers.length, cells.length);
    for (let i = 0; i < n; i++) {{
        const header = headers[i];
        const value = String(cells[i] || '').trim();
        if (!header || !isCellValue(value)) continue;
        out[header] = value;
    }}
    return out;
}}
function extractRowMetricValues(scrollRow, scrollContainer, allHeaders) {{
    const cellNodes = getSorterCellNodes(scrollRow);
    const headerValues = {{}};
    if (allHeaders.length && cellNodes.length === allHeaders.length) {{
        const cells = cellNodes.map((c) => norm(c.innerText || c.textContent || ''));
        Object.assign(headerValues, mapCellsToHeaders(cells, allHeaders));
        return headerValues;
    }}
    if (allHeaders.length && scrollContainer) {{
        for (let i = 0; i < cellNodes.length; i++) {{
            if (i >= allHeaders.length) break;
            const node = cellNodes[i];
            if (!isInScrollViewport(node, scrollContainer)) continue;
            const header = allHeaders[i];
            const value = norm(node.innerText || node.textContent || '');
            if (header && isCellValue(value)) headerValues[header] = value;
        }}
    }}
    return headerValues;
}}
function syncTableScroll(root, scrollEl, pos) {{
    if (scrollEl) scrollEl.scrollLeft = pos;
    if (!root) return;
    for (const sel of [
        '.anq-table-header',
        '.anq-table-sticky-scroll',
        '.ant-table-header',
        '.ant-table-sticky-scroll',
        '[class*="sticky-scroll"]',
    ]) {{
        for (const node of Array.from(root.querySelectorAll(sel))) {{
            if (!node || node === scrollEl) continue;
            try {{ node.scrollLeft = pos; }} catch (e) {{}}
        }}
    }}
}}
function findListTableRoot() {{
    const picker = document.querySelector('[class*="ListDatePicker"]');
    if (picker) {{
        let node = picker.parentElement;
        for (let i = 0; i < 12 && node; i++) {{
            const table = node.querySelector('.anq-table-wrapper, .anq-table, .ant-table-wrapper, .ant-table');
            if (table && isVisible(table)) return table;
            node = node.parentElement;
        }}
    }}
    const tbody = document.querySelector('.anq-table-tbody, .ant-table-tbody');
    if (tbody && isVisible(tbody)) {{
        return tbody.closest('.anq-table-wrapper, .anq-table, .ant-table-wrapper, .ant-table, table') || tbody;
    }}
    return null;
}}
function findFixedTbody(root) {{
    const fixed = root.querySelector(
        '.anq-table-fixed-left .anq-table-tbody, .anq-table-ping-left .anq-table-tbody, '
        + '.ant-table-fixed-left .ant-table-tbody'
    );
    if (fixed && isVisible(fixed)) return fixed;
    const tbodies = Array.from(root.querySelectorAll('.anq-table-tbody, .ant-table-tbody, tbody'));
    for (const tb of tbodies) {{
        if (!isVisible(tb)) continue;
        if (/商品\\s*ID/i.test(tb.innerText || '')) return tb;
    }}
    return root.querySelector('.anq-table-tbody, .ant-table-tbody, tbody');
}}
function findScrollContainer(root) {{
    const marked = document.querySelector('[{_SCROLL_MARK_ATTR}]');
    if (marked && isVisible(marked)) return marked;
    const selectors = [
        '.anq-table-body',
        '.anq-table-content',
        '.ant-table-body',
        '.ant-table-content',
        '[class*="table-content"]',
        '[class*="TableContent"]',
    ];
    let best = null;
    let bestOverflow = 0;
    for (const sel of selectors) {{
        for (const el of Array.from(root.querySelectorAll(sel))) {{
            if (!isVisible(el)) continue;
            if (el.closest('.anq-table-fixed-left, .anq-table-ping-left, .ant-table-fixed-left')) continue;
            const overflow = el.scrollWidth - el.clientWidth;
            if (overflow > bestOverflow) {{
                bestOverflow = overflow;
                best = el;
            }}
        }}
    }}
    if (best) return best;
    return root.querySelector('.anq-table-body, .anq-table-content, .ant-table-body') || root;
}}
function findScrollTbody(scrollContainer) {{
    const tbodies = Array.from(scrollContainer.querySelectorAll('.anq-table-tbody, .ant-table-tbody, tbody'));
    for (const tb of tbodies) {{
        if (!isVisible(tb)) continue;
        if (tb.closest('.anq-table-fixed-left, .anq-table-ping-left, .ant-table-fixed-left')) continue;
        return tb;
    }}
    return scrollContainer.querySelector('.anq-table-tbody, .ant-table-tbody, tbody');
}}
function extractAllScrollHeaders(root, scrollContainer) {{
    return extractScrollMetricHeaders(root);
}}
function parseUnifiedRow(row, scrollContainer, allHeaders) {{
    const rowText = norm(row.innerText || row.textContent || '');
    if (!rowText || rowText.includes('合计数据')) return null;
    const idMatch = rowText.match(/商品\\s*ID[：:]\\s*(\\d{{6,}})/i);
    if (!idMatch) return null;
    return {{
        product_id: idMatch[1],
        header_values: extractRowMetricValues(row, scrollContainer, allHeaders),
        row_text: rowText.slice(0, 200),
    }};
}}
const root = findListTableRoot();
if (!root) return {{ headers: [], rows: [], scroll_left: 0 }};
const scrollContainer = findScrollContainer(root);
const fixedTbody = findFixedTbody(root);
const scrollTbody = findScrollTbody(scrollContainer);
const allHeaders = extractAllScrollHeaders(root, scrollContainer);
const scrollLeft = scrollContainer.scrollLeft || 0;
const rows = [];
const seen = new Set();
if (fixedTbody && scrollTbody && fixedTbody !== scrollTbody) {{
    const fixedRows = Array.from(fixedTbody.querySelectorAll('tr.anq-table-row, tr')).filter(isVisible);
    const scrollRows = Array.from(scrollTbody.querySelectorAll('tr.anq-table-row, tr')).filter(isVisible);
    const count = Math.max(fixedRows.length, scrollRows.length);
    for (let i = 0; i < count; i++) {{
        const fixedText = norm(fixedRows[i]?.innerText || fixedRows[i]?.textContent || '');
        if (!fixedText || fixedText.includes('合计数据')) continue;
        const idMatch = fixedText.match(/商品\\s*ID[：:]\\s*(\\d{{6,}})/i);
        if (!idMatch || seen.has(idMatch[1])) continue;
        seen.add(idMatch[1]);
        rows.push({{
            product_id: idMatch[1],
            header_values: extractRowMetricValues(scrollRows[i], scrollContainer, allHeaders),
            row_text: fixedText.slice(0, 200),
        }});
    }}
}}
if (!rows.length && scrollTbody) {{
    for (const row of Array.from(scrollTbody.querySelectorAll('tr.anq-table-row, tr')).filter(isVisible)) {{
        const parsed = parseUnifiedRow(row, scrollContainer, allHeaders);
        if (!parsed || seen.has(parsed.product_id)) continue;
        seen.add(parsed.product_id);
        rows.push(parsed);
    }}
}}
return {{ headers: allHeaders, rows, scroll_left: scrollLeft }};
"""

_RESET_PROMOTION_TABLE_SCROLL_JS = f"""
(() => {{
    const el = document.querySelector('[{_SCROLL_MARK_ATTR}]');
    if (el) el.scrollLeft = 0;
    document.querySelectorAll('[{_SCROLL_MARK_ATTR}]').forEach((node) => {{
        node.removeAttribute('{_SCROLL_MARK_ATTR}');
    }});
}})();
"""


def _log(account_id: str, message: str) -> None:
    print(f"[{account_id}] {message}", flush=True)


def _fail(
    account_id: str,
    page: DpPage,
    *,
    error: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    url = _page_url(page)
    preview = _body_text(page).replace("\n", " ")[:200]
    _log(account_id, f"投流抓取失败：{message} | url={url}")
    if preview:
        _log(account_id, f"页面摘要：{preview}")
    return {"status": "failed", "error": error, "message": message, "url": url, **extra}


def _scroll_positions(max_scroll: int, step: int) -> list[int]:
    if max_scroll <= 0:
        return [0]
    step = max(200, int(step or 400))
    positions = [0]
    pos = step
    while pos < max_scroll:
        positions.append(pos)
        pos += step
    if positions[-1] != max_scroll:
        positions.append(max_scroll)
    return positions


def _set_promotion_table_scroll(page: DpPage, scroll_left: int) -> None:
    page.run_js(
        f"""
        (() => {{
            const pos = {int(scroll_left)};
            const el = document.querySelector('[{_SCROLL_MARK_ATTR}]');
            if (!el) return;
            const root = el.closest('.anq-table-wrapper, .anq-table, .ant-table-wrapper, .ant-table');
            el.scrollLeft = pos;
            if (!root) return;
            for (const sel of [
                '.anq-table-header',
                '.anq-table-sticky-scroll',
                '.ant-table-header',
                '.ant-table-sticky-scroll',
                '[class*="sticky-scroll"]',
            ]) {{
                for (const node of Array.from(root.querySelectorAll(sel))) {{
                    if (!node || node === el) continue;
                    try {{ node.scrollLeft = pos; }} catch (e) {{}}
                }}
            }}
        }})();
        """
    )


def _reset_promotion_table_scroll(page: DpPage) -> None:
    page.run_js(_RESET_PROMOTION_TABLE_SCROLL_JS)


def _extract_promotion_table(page: DpPage, account_id: str = "") -> dict[str, Any]:
    """从固定列 + 横向滚动列拆分表格中提取全部指标。"""
    prep = page.run_js(_PREPARE_PROMOTION_TABLE_JS) or {}
    if not prep.get("ready"):
        return {
            "ready": False,
            "headers": [],
            "rows": [],
            "reason": str(prep.get("reason") or "table_not_found"),
        }

    max_scroll = int(prep.get("max_scroll") or 0)
    step = int(prep.get("scroll_step") or 400)
    positions = _scroll_positions(max_scroll, step)

    merged_headers: list[str] = []
    merged_rows: dict[str, dict[str, Any]] = {}

    try:
        for pos in positions:
            _set_promotion_table_scroll(page, pos)
            time.sleep(0.35)
            slice_data = page.run_js(_EXTRACT_PROMOTION_TABLE_SLICE_JS) or {}
            for header in slice_data.get("headers") or []:
                text = normalize_traffic_header(str(header or "").strip())
                if text and is_known_metric_header(text) and text not in merged_headers:
                    merged_headers.append(text)
            for item in slice_data.get("rows") or []:
                if not isinstance(item, dict):
                    continue
                product_id = str(item.get("product_id") or "").strip()
                if not product_id:
                    continue
                bucket = merged_rows.setdefault(
                    product_id,
                    {"product_id": product_id, "header_values": {}, "row_text": ""},
                )
                header_values = item.get("header_values")
                if isinstance(header_values, dict):
                    bucket["header_values"].update(normalize_traffic_metrics(header_values))
                row_text = str(item.get("row_text") or "").strip()
                if row_text:
                    bucket["row_text"] = row_text[:500]
    finally:
        _reset_promotion_table_scroll(page)

    rows = list(merged_rows.values())
    if rows and account_id:
        sample = rows[0].get("header_values") or {}
        _log(
            account_id,
            f"表格解析：{len(rows)} 行，{len(merged_headers)} 列表头，"
            f"样例指标 {len(sample)} 个（横向扫描 {len(positions)} 次）",
        )
    return {
        "ready": bool(rows),
        "headers": merged_headers,
        "rows": rows,
        "row_count": len(rows),
        "scroll_positions": len(positions),
        "reason": "ok" if rows else "no_rows",
    }


def _probe_promotion_list_table(page: DpPage) -> dict[str, Any]:
    payload = _extract_promotion_table(page)
    payload["ready"] = bool(payload.get("rows"))
    return payload


def _is_promotion_list_url(url: str) -> bool:
    u = str(url or "")
    return "goods/promotion/list" in u or "/promotion/list" in u


def _read_consumption_date_state(page: DpPage, target_str: str) -> dict[str, Any]:
    return page.run_js(
        f"""
        function norm(text) {{
            return String(text || '').replace(/\\s+/g, ' ').trim();
        }}
        const target = '{target_str}';
        const pickerValues = [];
        for (const el of document.querySelectorAll('[class*="ListDatePicker_value"], [class*="ListDatePicker"]')) {{
            const t = norm(el.innerText || el.textContent || '');
            if (t.includes('~') && /\\d{{4}}\\/\\d{{1,2}}\\/\\d{{1,2}}/.test(t)) pickerValues.push(t);
        }}
        let pickerOk = false;
        let pickerValue = '';
        for (const v of pickerValues) {{
            const parts = v.split('~').map((x) => x.trim());
            if (parts.length >= 2 && parts[0].includes(target) && parts[1].includes(target)) {{
                pickerOk = true;
                pickerValue = v;
                break;
            }}
        }}
        const body = norm(document.body?.innerText || '');
        const countMatch = body.match(/合计数据\\s*\\(\\s*(\\d+)\\s*条\\s*\\)/);
        const rowCount = countMatch ? parseInt(countMatch[1], 10) : 0;
        const hasConsumptionLabel = body.includes('推广消耗时间');
        return {{
            pickerOk,
            pickerValue,
            pickerValues,
            rowCount,
            hasConsumptionLabel,
            onListPage: location.href.includes('goods/promotion/list') || location.href.includes('/promotion/list'),
        }};
        """
    ) or {}


def _close_promotion_tabs_keep_list(page: DpPage, account_id: str) -> dict[str, Any]:
    """只保留推广列表页标签，关闭其余标签。"""
    kept = None
    for item in _live_context_pages(page):
        try:
            if item.is_closed():
                continue
            url = str(item.url or "")
            if _is_promotion_list_url(url):
                kept = item
                break
        except Exception:
            continue

    if kept is None:
        return {"closed": [], "kept": False}

    closed_urls: list[str] = []
    for item in list(_live_context_pages(page)):
        if item is kept:
            continue
        try:
            if item.is_closed():
                continue
            url = str(item.url or "")
            item.close()
            closed_urls.append(url)
            _log(account_id, f"已关闭多余标签页: {url}")
        except Exception:
            continue

    _bind_page(page, kept)
    try:
        kept.bring_to_front()
    except Exception:
        pass
    time.sleep(0.5)
    return {"closed": closed_urls, "kept": True, "kept_url": str(getattr(kept, "url", "") or "")}


def _open_promotion_list_for_report(
    page: DpPage,
    account_id: str,
    *,
    account: AccountConfig | None = None,
) -> bool:
    """直达推广列表页，避免概况→查看全部推广多开标签。"""
    session = _ensure_session(page, account, account_id)
    if not session.get("logged_in"):
        return False

    _dismiss_message_popup(page)
    _log(account_id, f"直达推广列表页：{PROMOTION_LIST_URL}")
    try:
        page.get(PROMOTION_LIST_URL)
        time.sleep(4)
        _switch_to_latest_tab(page)
        _dismiss_message_popup(page)
        if is_login_url(_page_url(page)):
            relogin = _ensure_session(page, account, account_id)
            if not relogin.get("logged_in"):
                return False
            page.get(PROMOTION_LIST_URL)
            time.sleep(4)
            _switch_to_latest_tab(page)
    except Exception as exc:
        _log(account_id, f"直达推广列表页失败：{_safe_exc(exc)}")
        return False

    _close_mms_tabs_when_yingxiao_ready(page, account_id)
    cleanup = _close_promotion_tabs_keep_list(page, account_id)
    if cleanup.get("closed"):
        _log(account_id, f"已清理 {len(cleanup.get('closed') or [])} 个多余标签页")

    if _is_promotion_list_url(_page_url(page)):
        _log(account_id, f"推广列表页已就绪：{_page_url(page)}")
        return True

    _log(account_id, "直达失败，回退：推广概况 → 查看全部推广")
    if not _open_promotion_overview(page, account_id, account=account):
        return False
    time.sleep(2)
    if not _ensure_promotion_list_page(page, account_id):
        return False
    _close_mms_tabs_when_yingxiao_ready(page, account_id)
    _close_promotion_tabs_keep_list(page, account_id)
    return _is_promotion_list_url(_page_url(page))


def _navigate_promotion_list_direct(page: DpPage, account_id: str) -> bool:
    try:
        _log(account_id, f"尝试直达推广列表页：{PROMOTION_LIST_URL}")
        page.get(PROMOTION_LIST_URL)
        time.sleep(4)
        _switch_to_latest_tab(page)
        _dismiss_message_popup(page)
        if _is_promotion_list_url(_page_url(page)):
            _log(account_id, f"已直达推广列表页：{_page_url(page)}")
            return True
    except Exception as exc:
        _log(account_id, f"直达推广列表页失败：{_safe_exc(exc)}")
    return False


def _ensure_promotion_list_page(page: DpPage, account_id: str) -> bool:
    """必须进入 goods/promotion/list，概况页内嵌表格不能用于昨日筛选。"""
    _switch_to_latest_tab(page)
    if _is_promotion_list_url(_page_url(page)):
        _log(account_id, f"已在推广列表页：{_page_url(page)}")
        return True

    for attempt in range(3):
        _click_view_all_promotions(page, account_id)
        time.sleep(2)
        _switch_to_latest_tab(page)
        for _ in range(12):
            url = _page_url(page)
            if _is_promotion_list_url(url):
                _log(account_id, f"推广列表页已就绪：{url}")
                return True
            _switch_to_latest_tab(page)
            time.sleep(1)
        _log(account_id, f"第{attempt + 1}次点击「查看全部推广」后仍在：{_page_url(page)}")

    return _navigate_promotion_list_direct(page, account_id)


def _is_stable_cost_list_page(page: DpPage) -> bool:
    if not _is_promotion_list_url(_page_url(page)):
        return False
    probe = _probe_promotion_list_table(page)
    return bool(probe.get("ready"))


def _wait_after_view_all_promotions(page: DpPage, account_id: str, *, timeout: int = 25) -> bool:
    """点击「查看全部推广」后等待进入 goods/promotion/list。"""
    for _ in range(timeout):
        _switch_to_latest_tab(page)
        _dismiss_message_popup(page)
        url = _page_url(page)
        if _is_promotion_list_url(url):
            _log(account_id, f"推广列表页已就绪：{url}")
            return True
        time.sleep(1)
    _log(account_id, f"等待推广列表页超时：{_page_url(page)}")
    return False


def _click_view_all_promotions(page: DpPage, account_id: str) -> bool:
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
        for (const a of Array.from(document.querySelectorAll('a[href*="promotion/list"], a[href*="goods/promotion"]'))) {
            if (!isVisible(a)) continue;
            const text = (a.innerText || a.textContent || '').replace(/\\s+/g, '');
            if (!text.includes('查看全部推广')) continue;
            a.scrollIntoView({ block: 'center' });
            a.click();
            return { clicked: true, method: 'href_link', href: a.href || '' };
        }
        const nodes = Array.from(document.querySelectorAll('a,button,span,div'));
        for (const el of nodes) {
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
            if (text !== '查看全部推广') continue;
            const target = el.closest('a,button') || el;
            target.scrollIntoView({ block: 'center' });
            target.click();
            return { clicked: true, method: 'text_node' };
        }
        return { clicked: false };
        """
    ) or {}
    if result.get("clicked"):
        _log(account_id, f"已点击「查看全部推广」（{result.get('method') or 'unknown'}）")
        return True
    if _click_text(page, "查看全部推广", timeout=4):
        _log(account_id, "已通过文本点击「查看全部推广」")
        return True
    return False


def _ensure_stable_cost_tab(page: DpPage, account_id: str) -> bool:
    if _is_stable_cost_list_page(page):
        _log(account_id, "已在「稳定成本推广」列表（含数据表格）")
        return True

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
        const tabs = Array.from(document.querySelectorAll('[role="tab"],.ant-tabs-tab,div,span,a'));
        for (const el of tabs) {
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
            if (text !== '稳定成本推广') continue;
            const active = el.className?.includes?.('active')
                || el.getAttribute?.('aria-selected') === 'true'
                || el.closest?.('[aria-selected="true"]');
            if (active) return { switched: true, already: true };
            const target = el.closest('[role="tab"],.ant-tabs-tab,a,button') || el;
            target.scrollIntoView({ block: 'center' });
            target.click();
            return { switched: true, already: false };
        }
        return { switched: false };
        """
    ) or {}
    if result.get("switched"):
        if not result.get("already"):
            time.sleep(3)
        _log(account_id, "已切换到「稳定成本推广」页签")
        for _ in range(8):
            if _is_stable_cost_list_page(page):
                return True
            time.sleep(1)
        return True

    if _click_text(page, "稳定成本推广", timeout=4):
        time.sleep(3)
        _log(account_id, "已通过文本切换到「稳定成本推广」")
        return True

    return _is_stable_cost_list_page(page)


def _open_consumption_date_picker(page: DpPage) -> dict[str, Any]:
    """打开「推广消耗时间」日期范围选择器（表格上方，非顶部推广数据卡片）。"""
    return page.run_js(
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
            return String(text || '').replace(/\\s+/g, ' ').trim();
        }
        function clickPicker(picker, method) {
            const input = picker.querySelector('.anq-picker-input input, .anq-picker-input, input[placeholder*="日期"], input') || picker;
            input.click();
            return { clicked: true, method, label: norm(picker.innerText || '').slice(0, 60) };
        }
        const tableArea = document.querySelector('.anq-table, .anq-table-wrapper, [class*="ListDatePicker"]')?.closest('section, main, div');
        for (const picker of Array.from(document.querySelectorAll('[class*="ListDatePicker"], .anq-date-range-picker'))) {
            if (!isVisible(picker)) continue;
            if (!tableArea || !tableArea.contains(picker)) {
                const nearTable = !!picker.closest('[class*="list"], [class*="List"], main, section');
                const hasLabel = norm(picker.parentElement?.innerText || '').includes('推广消耗时间');
                if (!nearTable && !hasLabel) continue;
            }
            const text = norm(picker.innerText || picker.textContent || '');
            if (text.includes('~') || /\\d{4}\\/\\d{1,2}\\/\\d{1,2}/.test(text)) {
                return clickPicker(picker, 'list_date_picker');
            }
        }
        for (const el of Array.from(document.querySelectorAll('span,div,label'))) {
            if (!isVisible(el)) continue;
            const t = norm(el.innerText || el.textContent || '');
            if (t !== '推广消耗时间' && !t.startsWith('推广消耗时间')) continue;
            let node = el.parentElement;
            for (let i = 0; i < 6 && node; i++) {
                const picker = node.querySelector('[class*="ListDatePicker"], .anq-date-range-picker');
                if (picker && isVisible(picker)) {
                    return clickPicker(picker, 'consumption_time_label');
                }
                node = node.parentElement;
            }
        }
        for (const input of Array.from(document.querySelectorAll('.anq-picker-input input, input[placeholder="开始日期"]'))) {
            if (!isVisible(input)) continue;
            const rect = input.getBoundingClientRect();
            if (rect.top < 120 || rect.top > window.innerHeight * 0.75) continue;
            (input.closest('.anq-picker, .anq-date-range-picker, [class*="ListDatePicker"]') || input).click();
            return { clicked: true, method: 'start_date_input', label: String(input.value || '') };
        }
        return { clicked: false };
        """
    ) or {"clicked": False}


def _click_yesterday_in_date_panel(page: DpPage) -> dict[str, Any]:
    """在日期面板内点击「昨日」快捷项（anq-range-picker-quick-selection-item）。"""
    return page.run_js(
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
            return String(text || '').replace(/\\s+/g, '').trim();
        }
        const panels = Array.from(document.querySelectorAll(
            '.anq-picker-dropdown, .anq-range-picker-dropdown, .anq-picker-panel-container, [class*="picker-dropdown"], [class*="picker-panel"]'
        )).filter(isVisible);
        const scopes = panels.length ? panels : [document.body];
        for (const scope of scopes) {
            const items = Array.from(scope.querySelectorAll(
                '.anq-range-picker-quick-selection-item, [class*="quick-selection-item"]'
            ));
            for (const el of items) {
                if (!isVisible(el)) continue;
                if (norm(el.innerText || el.textContent || '') !== '昨日') continue;
                el.click();
                return { clicked: true, method: 'quick_selection_item' };
            }
        }
        return { clicked: false, reason: 'yesterday_panel_item_not_found' };
        """
    ) or {"clicked": False}


def _wait_consumption_date_applied(page: DpPage, target_str: str, *, timeout: int = 15) -> dict[str, Any]:
    """等待推广消耗时间日期范围变为 target ~ target，并读取合计条数。"""
    last: dict[str, Any] = {}
    for _ in range(timeout):
        payload = _read_consumption_date_state(page, target_str)
        last = payload
        if payload.get("pickerOk"):
            return payload
        time.sleep(1)
    return last


def _apply_yesterday_consumption_date_once(page: DpPage, account_id: str) -> bool:
    opened = _open_consumption_date_picker(page)
    if opened.get("clicked"):
        _log(account_id, f"已打开推广消耗时间选择器（{opened.get('method')}）")
        time.sleep(1)
    else:
        _log(account_id, "未找到推广消耗时间选择器")
        return False

    clicked = _click_yesterday_in_date_panel(page)
    if not clicked.get("clicked"):
        opened = _open_consumption_date_picker(page)
        time.sleep(0.8)
        clicked = _click_yesterday_in_date_panel(page)
    if not clicked.get("clicked"):
        _log(account_id, "日期面板内未找到「昨日」快捷项")
        return False

    time.sleep(2)
    page.run_js(
        """
        const panels = Array.from(document.querySelectorAll('.anq-picker-dropdown, .anq-picker-panel-container'))
            .filter(el => el.getBoundingClientRect().width > 0);
        if (panels.length) document.body.click();
        """
    )
    time.sleep(1)
    return True


def _select_yesterday_report_range(
    page: DpPage,
    account_id: str,
    *,
    report_date: date | None = None,
) -> bool:
    """选择「推广消耗时间 → 昨日」（必须在 goods/promotion/list 页面）。"""
    if not _is_promotion_list_url(_page_url(page)):
        _log(account_id, f"当前不在推广列表页，无法筛选昨日：{_page_url(page)}")
        return False

    target = report_date or (date.today() - timedelta(days=1))
    target_str = target.strftime("%Y/%m/%d")

    before = _read_consumption_date_state(page, target_str)
    if before.get("pickerOk"):
        _log(account_id, f"推广消耗时间已是昨日：{before.get('pickerValue') or target_str}")
        return True

    for attempt in range(2):
        if not _apply_yesterday_consumption_date_once(page, account_id):
            continue
        state = _wait_consumption_date_applied(page, target_str, timeout=12)
        if state.get("pickerOk"):
            row_count = int(state.get("rowCount") or 0)
            _log(
                account_id,
                f"已选择推广消耗时间「昨日」({state.get('pickerValue') or target_str})"
                + (f"，合计 {row_count} 条" if row_count else ""),
            )
            return True
        _log(
            account_id,
            f"第{attempt + 1}次选择昨日未生效，当前：{state.get('pickerValues') or state.get('pickerValue') or '-'}",
        )

    _log(account_id, f"推广消耗时间未切换到 {target_str}")
    return False


def _wait_promotion_table_ready(
    page: DpPage,
    account_id: str,
    *,
    min_rows: int = 1,
    timeout: int = 20,
) -> bool:
    """等待推广列表表格加载出可解析的商品行。"""
    for attempt in range(timeout):
        payload = _extract_promotion_table(page, account_id)
        rows = payload.get("rows") or []
        metric_rows = sum(
            1
            for row in rows
            if isinstance(row, dict) and len(dict(row.get("header_values") or {})) > 0
        )
        if len(rows) >= min_rows and metric_rows >= min(1, len(rows)):
            _log(
                account_id,
                f"表格已加载：{len(rows)} 行，含指标 {metric_rows} 行",
            )
            return True
        if rows and attempt >= 8:
            _log(account_id, f"表格已有 {len(rows)} 行但指标仍为空，继续等待({attempt + 1}/{timeout})")
        time.sleep(1)
    return False


def _scrape_current_page_rows(page: DpPage, account_id: str = "") -> tuple[list[dict[str, Any]], list[str]]:
    payload = _extract_promotion_table(page, account_id)
    return list(payload.get("rows") or []), list(payload.get("headers") or [])


def _parse_rows_with_headers(raw_rows: list[dict[str, Any]], headers: list[str]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for item in raw_rows:
        product_id = str(item.get("product_id") or "").strip()
        if not product_id:
            continue
        header_values = normalize_traffic_metrics(dict(item.get("header_values") or {}))
        parsed.append(
            {
                "product_id": product_id,
                "metrics": header_values,
                "header_values": header_values,
                "row_text": str(item.get("row_text") or "")[:500],
            }
        )
    return parsed


def _scrape_all_pages(page: DpPage, account_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    all_rows: list[dict[str, Any]] = []
    headers: list[str] = []
    seen_ids: set[str] = set()

    for page_no in range(1, MAX_PAGES + 1):
        raw_rows, page_headers = _scrape_current_page_rows(page, account_id)
        if page_headers:
            headers = page_headers

        parsed = _parse_rows_with_headers(raw_rows, headers)
        new_count = 0
        for row in parsed:
            pid = row["product_id"]
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            all_rows.append(row)
            new_count += 1

        summary = _read_pagination_summary(page)
        metric_count = sum(len(row.get("metrics") or {}) for row in parsed)
        _log(
            account_id,
            f"投流数据第{page_no}页：本页{len(parsed)}条，有效指标{metric_count}条，新增{new_count}条，累计{len(all_rows)}条"
            + (f"；{summary}" if summary else ""),
        )
        if page_no >= MAX_PAGES:
            break
        if not _go_next_page(page, account_id):
            break
        time.sleep(1.5)

    return all_rows, headers


def scrape_stable_cost_promotion_report(
    page: DpPage,
    account_id: str,
    *,
    account: AccountConfig | None = None,
    report_date: date | None = None,
) -> dict[str, Any]:
    """抓取稳定成本推广「昨日」报表（全部分页）。"""
    target_date = report_date or (date.today() - timedelta(days=1))
    session = _ensure_session(page, account, account_id)
    if not session.get("logged_in"):
        return {
            "status": "failed",
            "error": "login_required",
            "message": "推广投流抓取前未登录",
        }

    _dismiss_message_popup(page)
    if not _open_promotion_list_for_report(page, account_id, account=account):
        return _fail(
            account_id,
            page,
            error="promotion_list_not_ready",
            message="未能进入推广列表页 goods/promotion/list",
        )

    if not _ensure_stable_cost_tab(page, account_id):
        return _fail(
            account_id,
            page,
            error="stable_cost_tab_not_found",
            message="未能进入「稳定成本推广」列表",
        )

    time.sleep(2)
    if not _select_yesterday_report_range(page, account_id, report_date=target_date):
        return _fail(
            account_id,
            page,
            error="yesterday_filter_not_found",
            message="未能选择「推广消耗时间 → 昨日」",
        )

    time.sleep(2)
    state = _read_consumption_date_state(page, target_date.strftime("%Y/%m/%d"))
    if not state.get("pickerOk"):
        return _fail(
            account_id,
            page,
            error="yesterday_not_applied",
            message="推广消耗时间未切换到昨日",
            state=state,
        )
    expected = int(state.get("rowCount") or 0)
    if expected:
        _log(account_id, f"表格合计数据：{expected} 条")
    if not _wait_promotion_table_ready(page, account_id, min_rows=max(1, expected)):
        _log(account_id, "警告：表格数据加载较慢，将尝试继续抓取")

    rows, headers = _scrape_all_pages(page, account_id)
    if expected and len(rows) != expected:
        _log(
            account_id,
            f"警告：抓取 {len(rows)} 条，页面合计 {expected} 条，请检查分页或日期筛选",
        )
    if not rows:
        probe = _probe_promotion_list_table(page)
        if not probe.get("rows"):
            return _fail(
                account_id,
                page,
                error="promotion_table_not_found",
                message="未找到含商品ID与花费指标的推广表格",
                probe=probe,
            )

    _log(account_id, f"投流昨日数据抓取完成：{len(rows)} 条，日期={target_date.isoformat()}")
    if not rows:
        _log(account_id, "警告：表格无数据行，请确认店铺昨日是否有稳定成本推广")

    return {
        "status": "success",
        "report_date": target_date.isoformat(),
        "url": _page_url(page),
        "headers": headers,
        "rows": rows,
        "total": len(rows),
    }

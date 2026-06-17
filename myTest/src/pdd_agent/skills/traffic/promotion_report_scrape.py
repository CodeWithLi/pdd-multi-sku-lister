"""推广平台：推广概况 → 查看全部推广 → 稳定成本推广 → 昨日数据抓取。"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.config import AccountConfig
from pdd_agent.skills.campaign.limited_time import (
    _body_text,
    _click_text,
    _dismiss_message_popup,
    _safe_exc,
    _switch_to_latest_tab,
)
from pdd_agent.skills.delist.automation import _go_next_page, _read_pagination_summary
from pdd_agent.skills.traffic.promotion_create import (
    _ensure_session,
    _open_promotion_overview,
    _page_url,
)

MAX_PAGES = 200
PROMOTION_LIST_URL = "https://yingxiao.pinduoduo.com/goods/promotion/list"

PRODUCT_ID_PATTERN = re.compile(r"商品\s*ID[：:]\s*(\d{6,})", re.IGNORECASE)

_EXTRACT_PROMOTION_TABLE_JS = """
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
    return String(text || '').replace(/\\s+/g, ' ').trim();
}
function hasProductId(text) {
    return /商品\\s*ID/i.test(String(text || ''));
}
function hasSpendMetric(text) {
    const t = String(text || '');
    return t.includes('成交花费') || t.includes('总花费') || t.includes('花费(元)');
}
function findListTableRoot() {
    const tbody = document.querySelector('.anq-table-tbody');
    if (tbody && isVisible(tbody)) {
        return tbody.closest('.anq-table, .anq-table-wrapper, table') || tbody;
    }
    const picker = document.querySelector('[class*="ListDatePicker"]');
    if (picker) {
        let node = picker.parentElement;
        for (let i = 0; i < 10 && node; i++) {
            const table = node.querySelector('.anq-table, .anq-table-wrapper');
            if (table && isVisible(table)) return table;
            node = node.parentElement;
        }
    }
    return null;
}
function normalizeHeader(h) {
    return String(h || '').replace(/\\s+/g, '');
}
function isMetricValue(v) {
    const s = String(v == null ? '' : v).trim();
    if (!s || s === '-') return false;
    return /^-?\\d+(?:\\.\\d+)?$/.test(s);
}
function buildMetricColIndex(headers) {
    const index = {};
    const rules = [
        ['cost_per_order', '每笔净成交花费'],
        ['net_orders', '净成交笔数'],
        ['net_roi', '净实际投产比'],
        ['net_amount', '净交易额'],
        ['total_cost', '总花费'],
        ['roi', '实际投产比'],
        ['amount', '交易额'],
        ['spend', '成交花费'],
    ];
    for (let i = 0; i < headers.length; i++) {
        const h = normalizeHeader(headers[i]);
        for (const [key, kw] of rules) {
            if (index[key] !== undefined) continue;
            if (h.includes(kw)) index[key] = i;
        }
    }
    return index;
}
function extractHeaders(root) {
    const headerCells = Array.from(root.querySelectorAll(
        '.anq-table-thead .anq-table-cell, .anq-table-thead th, thead th, .ant-table-thead th'
    )).filter(isVisible);
    if (headerCells.length) {
        return headerCells.map((th) => norm(th.innerText || th.textContent || ''));
    }
    const headerRow = Array.from(root.querySelectorAll('tr, [class*="header-row"], [class*="table-head"]'))
        .find((row) => isVisible(row) && hasSpendMetric(row.innerText || ''));
    if (headerRow) {
        const cells = Array.from(headerRow.querySelectorAll('th, td, .ant-table-cell, [class*="cell"]'));
        if (cells.length) return cells.map((c) => norm(c.innerText || c.textContent || ''));
    }
    return [];
}
function getAlignedCells(row, headerCount) {
    let cells = Array.from(row.querySelectorAll(':scope > .anq-table-cell, :scope > td'))
        .filter(isVisible)
        .map((c) => norm(c.innerText || c.textContent || ''));
    if (!cells.length) {
        cells = Array.from(row.querySelectorAll('.anq-table-cell, td'))
            .filter(isVisible)
            .map((c) => norm(c.innerText || c.textContent || ''));
    }
    if (headerCount > 0 && cells.length > headerCount) {
        cells = cells.slice(cells.length - headerCount);
    }
    return cells;
}
function extractMetrics(cells, colIndex) {
    const metrics = {};
    for (const [key, idx] of Object.entries(colIndex)) {
        const i = parseInt(idx, 10);
        if (i >= cells.length) continue;
        const v = String(cells[i] || '').trim();
        if (isMetricValue(v)) metrics[key] = v;
    }
    return metrics;
}
function parseRow(row, headers, colIndex) {
    const rowText = norm(row.innerText || row.textContent || '');
    if (!rowText || rowText.includes('合计数据')) return null;
    const idMatch = rowText.match(/商品\\s*ID[：:]\\s*(\\d{6,})/i);
    if (!idMatch) return null;
    const cells = getAlignedCells(row, headers.length);
    const metrics = extractMetrics(cells, colIndex);
    return {
        product_id: idMatch[1],
        cells,
        metrics,
        row_text: rowText,
    };
}
function collectRows(root, headers, colIndex) {
    const selectors = [
        '.anq-table-tbody tr',
        '.anq-table-row',
        'tbody tr',
        '.ant-table-tbody tr',
        '.ant-table-tbody .ant-table-row',
        '.ant-table-row',
        '[class*="table-body"] tr',
        '[class*="table-body"] [class*="row"]',
        '[class*="TableBody"] [class*="row"]',
    ];
    const seen = new Set();
    const rows = [];
    for (const sel of selectors) {
        for (const row of Array.from(root.querySelectorAll(sel)).filter(isVisible)) {
            const parsed = parseRow(row, headers, colIndex);
            if (!parsed || seen.has(parsed.product_id)) continue;
            seen.add(parsed.product_id);
            rows.push(parsed);
        }
        if (rows.length) break;
    }
    return rows;
}
function findRoots() {
    const listTable = findListTableRoot();
    if (listTable) return [listTable];
    const nodes = Array.from(document.querySelectorAll('.anq-table,.anq-table-wrapper,table,.ant-table,[class*="table"],[class*="list"],main,section,div'));
    const scored = [];
    for (const el of nodes) {
        if (!isVisible(el)) continue;
        const text = norm(el.innerText || '');
        if (!hasProductId(text) || !hasSpendMetric(text)) continue;
        const rect = el.getBoundingClientRect();
        scored.push({ el, score: rect.width * rect.height });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.map((x) => x.el);
}
function fallbackRows(headers, colIndex) {
    const scope = findListTableRoot() || document.querySelector('.anq-table, .anq-table-wrapper');
    if (!scope) return [];
    const rows = [];
    const seen = new Set();
    for (const row of Array.from(scope.querySelectorAll('.anq-table-tbody tr, tbody tr, .anq-table-row')).filter(isVisible)) {
        const parsed = parseRow(row, headers, colIndex);
        if (!parsed || seen.has(parsed.product_id)) continue;
        seen.add(parsed.product_id);
        rows.push(parsed);
    }
    return rows;
}

const roots = findRoots();
let headers = [];
let colIndex = {};
let rows = [];
for (const root of roots) {
    headers = extractHeaders(root);
    colIndex = buildMetricColIndex(headers);
    rows = collectRows(root, headers, colIndex);
    if (rows.length) break;
}
if (!rows.length) {
    if (!headers.length) {
        for (const root of roots) {
            headers = extractHeaders(root);
            if (headers.length) break;
        }
        colIndex = buildMetricColIndex(headers);
    }
    rows = fallbackRows(headers, colIndex);
}
if (!headers.length && rows.length) {
    headers = ['成交花费(元)','交易额(元)','实际投产比','总花费(元)','净交易额(元)','净实际投产比','净成交笔数','每笔净成交花费(元)'];
}
return {
    ready: rows.length > 0 || (roots.length > 0 && hasProductId(document.body?.innerText || '') && hasSpendMetric(document.body?.innerText || '')),
    headers,
    rows,
    row_count: rows.length,
    root_count: roots.length,
    reason: rows.length ? 'ok' : 'table_not_found',
};
"""

METRIC_HEADERS: dict[str, str] = {
    "成交花费": "spend",
    "交易额": "amount",
    "实际投产比": "roi",
    "总花费": "total_cost",
    "净交易额": "net_amount",
    "净实际投产比": "net_roi",
    "净成交笔数": "net_orders",
    "每笔净成交花费": "cost_per_order",
}


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


def _extract_promotion_table(page: DpPage) -> dict[str, Any]:
    return page.run_js(_EXTRACT_PROMOTION_TABLE_JS) or {
        "ready": False,
        "headers": [],
        "rows": [],
        "reason": "extract_failed",
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


def _scrape_current_page_rows(page: DpPage) -> tuple[list[dict[str, Any]], list[str]]:
    payload = _extract_promotion_table(page)
    return list(payload.get("rows") or []), list(payload.get("headers") or [])


def _normalize_header(header: str) -> str:
    return re.sub(r"\s+", "", str(header or ""))


def _map_row_metrics(headers: list[str], cells: list[str]) -> dict[str, str]:
    metrics: dict[str, str] = {}
    normalized_headers = [_normalize_header(h) for h in headers]
    # 优先匹配更长的表头关键字，避免「每笔净成交花费」被「成交花费」误匹配。
    ordered_keys = sorted(METRIC_HEADERS.items(), key=lambda item: len(item[0]), reverse=True)
    for idx, header in enumerate(normalized_headers):
        if idx >= len(cells):
            continue
        value = str(cells[idx] or "").strip()
        if value == "" or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
            continue
        for key, field in ordered_keys:
            if key in header:
                metrics[field] = value
                break
    return metrics


def _parse_rows_with_headers(raw_rows: list[dict[str, Any]], headers: list[str]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for item in raw_rows:
        product_id = str(item.get("product_id") or "").strip()
        if not product_id:
            continue
        cells = list(item.get("cells") or [])
        metrics = dict(item.get("metrics") or {})
        if not metrics:
            metrics = _map_row_metrics(headers, cells)
        if not metrics:
            metrics = _parse_metrics_from_text(str(item.get("row_text") or ""))
        parsed.append(
            {
                "product_id": product_id,
                "metrics": metrics,
                "row_text": str(item.get("row_text") or "")[:500],
            }
        )
    return parsed


def _parse_metrics_from_text(row_text: str) -> dict[str, str]:
    """表头映射失败时，从行文本按字段名或数值顺序兜底解析（含 0.00）。"""
    text = str(row_text or "")
    patterns: list[tuple[str, str]] = [
        (r"成交花费(?:\(元\))?\s*([\d.]+|-)", "spend"),
        (r"交易额(?:\(元\))?\s*([\d.]+|-)", "amount"),
        (r"实际投产比\s*([\d.]+|-)", "roi"),
        (r"总花费(?:\(元\))?\s*([\d.]+|-)", "total_cost"),
        (r"净交易额(?:\(元\))?\s*([\d.]+|-)", "net_amount"),
        (r"净实际投产比\s*([\d.]+|-)", "net_roi"),
        (r"净成交笔数\s*(\d+|-)", "net_orders"),
        (r"每笔净成交花费(?:\(元\))?\s*([\d.]+|-)", "cost_per_order"),
    ]
    metrics: dict[str, str] = {}
    for pattern, field in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = str(match.group(1) or "").strip()
        if value == "-" or value == "":
            continue
        metrics[field] = value
    if len(metrics) >= 3:
        return metrics

    match = PRODUCT_ID_PATTERN.search(text)
    tail = text[match.end() :] if match else text
    tail = re.sub(r"\d{4}/\d{1,2}/\d{1,2}", " ", tail)
    tail = re.sub(r"净目标投产比[:：]\s*[\d.]+", " ", tail)
    tail = re.sub(r"预算日限额[:：][^\d]*", " ", tail)
    values = re.findall(r"\d+\.\d{2}|\b0\b", tail)
    keys = list(METRIC_HEADERS.values())
    if len(values) >= 4:
        return {keys[i]: values[i] for i in range(min(len(values), len(keys)))}
    return metrics


def _scrape_all_pages(page: DpPage, account_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    all_rows: list[dict[str, Any]] = []
    headers: list[str] = []
    seen_ids: set[str] = set()

    for page_no in range(1, MAX_PAGES + 1):
        raw_rows, page_headers = _scrape_current_page_rows(page)
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
        _log(
            account_id,
            f"投流数据第{page_no}页：本页{len(parsed)}条，新增{new_count}条，累计{len(all_rows)}条"
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
    if not _open_promotion_overview(page, account_id, account=account):
        return _fail(
            account_id,
            page,
            error="promotion_overview_not_found",
            message="未能进入推广概况页",
        )

    time.sleep(2)
    if not _ensure_promotion_list_page(page, account_id):
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
    page.run_js("window.scrollTo(0, document.body.scrollHeight * 0.35);")
    time.sleep(1)

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

"""从拼多多商品详情页只读抓取「规格与库存」——严禁修改任何商品数据。"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.logging import get_logger
from pdd_agent.skills.published.pdd_sku_normalize import normalize_pdd_lookup_skus

logger = get_logger(__name__)

GOODS_DETAIL_URLS = (
    "https://mms.pinduoduo.com/goods/goods_detail?goods_id={product_id}",
    "https://mms.pinduoduo.com/goods/goods_detail?id={product_id}",
)

_REQUIRED_FIELDS = (
    "style_name",
    "package_name",
    "group_price",
    "single_price",
    "spec_code",
)

_WAIT_READ_READY_JS = """
const body = (document.body && document.body.innerText) || '';
if (!body || body.length < 80) return false;
if (body.includes('加载中') && !body.includes('规格与库存') && !body.includes('拼单价')) return false;
for (const item of document.querySelectorAll('.goods-detail-item')) {
    const title = (item.querySelector('.item-title')?.innerText || '').trim();
    if (title !== '规格与库存' && title !== '价格及库存') continue;
    const text = (item.innerText || '');
    if (text.includes('拼单价')) return true;
}
return body.includes('规格与库存') && body.includes('拼单价');
"""

_SCROLL_TO_SPEC_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.display !== 'none' && s.visibility !== 'hidden';
}
for (const item of document.querySelectorAll('.goods-detail-item')) {
    const title = (item.querySelector('.item-title')?.innerText || '').trim();
    if (title !== '规格与库存' && title !== '价格及库存') continue;
    item.scrollIntoView({ block: 'center', inline: 'nearest' });
    return true;
}
window.scrollBy(0, 1200);
return false;
"""

_DIAGNOSE_AND_PARSE_JS = """
function norm(text) {
    return String(text || '').replace(/\\s+/g, ' ').trim();
}
function readCell(cell) {
    if (!cell) return '';
    return norm(cell.innerText || cell.textContent || '');
}
function pickPrice(text) {
    const m = String(text || '').match(/\\d+(?:\\.\\d+)?/);
    return m ? m[0] : '';
}
function looksLikeSpecCode(text) {
    const t = String(text || '').replace(/\\s+/g, '').toUpperCase();
    return /^[A-Z]{1,4}\\d{3}[A-Z0-9]*(\\+[A-Z0-9]+)*$/.test(t);
}
function resolveDimKeys(headers) {
    let dim1Key = '';
    let dim2Key = '';
    for (const h of headers) {
        const t = norm(h);
        if (!dim1Key && t.includes('款式')) dim1Key = '款式';
        if (!dim1Key && t.includes('尺寸')) dim1Key = '尺寸';
    }
    for (const h of headers) {
        const t = norm(h);
        if (t.includes('预览图') || t.includes('规格编码') || t.includes('商家编码')) continue;
        if (t.includes('套餐')) { dim2Key = '套餐'; break; }
        if (t === '规格' || (t.includes('规格') && !t.includes('编码'))) { dim2Key = '规格'; break; }
        if (t.includes('型号')) { dim2Key = '型号'; break; }
        if (t.includes('尺寸') && dim1Key !== '尺寸') { dim2Key = '尺寸'; break; }
    }
    if (!dim1Key) dim1Key = '款式';
    return { dim1_key: dim1Key, dim2_key: dim2Key || '套餐' };
}
function mapHeader(text) {
    const t = norm(text);
    if (!t) return 'skip';
    if (t.includes('预览图') || t === '预览') return 'skip';
    if (t.includes('上下架') || t === '库存' || t === '活动价') return 'skip';
    if (t.includes('款式')) return 'style';
    if (t.includes('套餐')) return 'package';
    if (t.includes('尺寸') || t.includes('型号')) return 'package';
    if (t.includes('拼单价')) return 'group_price';
    if (t.includes('单买价')) return 'single_price';
    if (t.includes('规格编码') || t.includes('商家编码')) return 'spec_code';
    return 'skip';
}
function buildColumnTypes(headers) {
    return headers.map((h) => mapHeader(h));
}
function parseRowByColumns(cells, currentStyle, colTypes) {
    const item = {
        style_name: '',
        package_name: '',
        group_price: '',
        single_price: '',
        spec_code: '',
    };
    if (!colTypes.length) return item;

    let cellIdx = 0;
    let colIdx = 0;
    const missingStyleCol = colTypes[0] === 'style' && cells.length < colTypes.length;
    if (missingStyleCol) {
        item.style_name = currentStyle || '';
        colIdx = 1;
    }

    for (; colIdx < colTypes.length && cellIdx < cells.length; colIdx++) {
        const field = colTypes[colIdx];
        const cell = cells[cellIdx];
        const v = readCell(cell);
        if (field === 'style') {
            if (v) item.style_name = v;
            else if (currentStyle) item.style_name = currentStyle;
            cellIdx++;
        } else if (field === 'package') {
            if (v && v !== '预览' && !v.includes('已上架')) item.package_name = v;
            cellIdx++;
        } else if (field === 'group_price') {
            if (v) item.group_price = pickPrice(v);
            cellIdx++;
        } else if (field === 'single_price') {
            if (v) item.single_price = pickPrice(v);
            cellIdx++;
        } else if (field === 'spec_code') {
            const code = v.replace(/\\s+/g, '').toUpperCase();
            if (looksLikeSpecCode(code)) item.spec_code = code;
            cellIdx++;
        } else {
            cellIdx++;
        }
    }

    if (!item.style_name && currentStyle) item.style_name = currentStyle;
    if (!item.spec_code) {
        for (const cell of cells) {
            const code = readCell(cell).replace(/\\s+/g, '').toUpperCase();
            if (looksLikeSpecCode(code)) {
                item.spec_code = code;
                break;
            }
        }
    }
    return item;
}
function isHeaderRow(text) {
    return text.includes('拼单价') && (text.includes('规格编码') || text.includes('商家编码') || text.includes('款式'));
}
function findSpecSection() {
    for (const item of document.querySelectorAll('.goods-detail-item')) {
        const title = (item.querySelector('.item-title')?.innerText || '').trim();
        if (title === '规格与库存' || title === '价格及库存') return item;
    }
    for (const item of document.querySelectorAll('.goods-detail-item')) {
        const text = norm(item.innerText || '');
        if (text.includes('拼单价') && (text.includes('规格编码') || text.includes('商家编码'))) return item;
    }
    return null;
}
function collectDataRows(section) {
    const rows = [];
    const seen = new Set();
    const push = (tr) => {
        if (!tr || seen.has(tr)) return;
        seen.add(tr);
        rows.push(tr);
    };
    const scopes = [section];
    const body = section.querySelector('.item-body, .item_body');
    if (body) scopes.push(body);
    const skuWrap = section.querySelector('.item-list-skus');
    if (skuWrap) scopes.push(skuWrap);
    for (const scope of scopes) {
        for (const tr of scope.querySelectorAll('tbody tr')) push(tr);
        for (const tr of scope.querySelectorAll('div[class*="tbody"] tr')) push(tr);
        for (const tr of scope.querySelectorAll('tr[data-testid="beast-core-table-body-tr"]')) push(tr);
        for (const tr of scope.querySelectorAll('table tr')) push(tr);
    }
    return rows;
}
function findSpecTable(section) {
    let best = null;
    let bestScore = 0;
    for (const table of section.querySelectorAll('table')) {
        const text = norm(table.innerText || '');
        if (!text.includes('拼单价')) continue;
        let score = text.length;
        if (text.includes('款式')) score += 500;
        if (text.includes('规格编码') || text.includes('商家编码')) score += 300;
        if (score > bestScore) { bestScore = score; best = table; }
    }
    return best;
}

const debug = {
    url: location.href,
    body_has_loading: ((document.body?.innerText) || '').includes('加载中'),
    body_has_spec_title: ((document.body?.innerText) || '').includes('规格与库存'),
    body_has_group_price: ((document.body?.innerText) || '').includes('拼单价'),
    item_titles: Array.from(document.querySelectorAll('.goods-detail-item .item-title'))
        .map(el => norm(el.innerText)).filter(Boolean).slice(0, 12),
    section_found: false,
    section_title: '',
    table_found: false,
    header_cells: [],
    row_total: 0,
    row_skipped_header: 0,
    row_skipped_short: 0,
    row_skipped_empty: 0,
    row_parsed: 0,
    sample_rows: [],
};

const section = findSpecSection();
debug.section_found = Boolean(section);
if (section) {
    debug.section_title = norm(section.querySelector('.item-title')?.innerText || '');
}

if (!section) {
    return { skus: [], error: 'spec_section_not_found', debug };
}

const table = findSpecTable(section);
debug.table_found = Boolean(table);
const headerRow = table ? (table.querySelector('thead tr') || table.querySelector('tr')) : null;
let dimKeys = { dim1_key: '款式', dim2_key: '套餐' };
if (headerRow) {
    debug.header_cells = Array.from(headerRow.querySelectorAll('th, td')).map(readCell).slice(0, 12);
    dimKeys = resolveDimKeys(debug.header_cells);
}
debug.spec_dim1_key = dimKeys.dim1_key;
debug.spec_dim2_key = dimKeys.dim2_key;
const colTypes = buildColumnTypes(debug.header_cells);

const rows = collectDataRows(section);
debug.row_total = rows.length;

let currentStyle = '';
const skus = [];
for (const tr of rows) {
    const rowText = norm(tr.innerText || '');
    if (!rowText) continue;
    if (isHeaderRow(rowText)) { debug.row_skipped_header++; continue; }
    const cells = Array.from(tr.querySelectorAll('td'));
    if (cells.length < 2) { debug.row_skipped_short++; continue; }

    const item = parseRowByColumns(cells, currentStyle, colTypes);
    if (item.style_name) currentStyle = item.style_name;

    const ok = item.spec_code || item.group_price || item.package_name;
    if (!ok) {
        debug.row_skipped_empty++;
        if (debug.sample_rows.length < 4) {
            debug.sample_rows.push({
                cell_count: cells.length,
                texts: cells.map(readCell).slice(0, 8),
                reason: 'no_spec_code_or_price',
            });
        }
        continue;
    }
    debug.row_parsed++;
    if (debug.sample_rows.length < 4) {
        debug.sample_rows.push({ parsed: item, cell_count: cells.length });
    }
    skus.push({
        style_name: item.style_name || currentStyle || '',
        package_name: item.package_name || '',
        group_price: item.group_price || '',
        single_price: item.single_price || '',
        spec_code: item.spec_code || '',
        spec_dim1_key: dimKeys.dim1_key,
        spec_dim1_value: item.style_name || currentStyle || '',
        spec_dim2_key: item.package_name ? dimKeys.dim2_key : '',
        spec_dim2_value: item.package_name || '',
        spec_count: item.package_name ? 2 : (item.style_name || currentStyle ? 1 : 0),
    });
}

const dedup = [];
const seen = new Set();
for (const sku of skus) {
    const key = [sku.spec_code, sku.package_name, sku.group_price].join('|');
    if (seen.has(key)) continue;
    seen.add(key);
    dedup.push(sku);
}

debug.dedup_count = dedup.length;
return {
    skus: dedup,
    error: dedup.length ? '' : 'spec_rows_empty',
    debug,
};
"""


def _log_debug(product_id: str, steps: list[dict[str, Any]], debug: dict[str, Any] | None) -> None:
    logger.info("[%s] scrape steps: %s", product_id, steps)
    if debug:
        logger.info(
            "[%s] scrape debug: section=%s table=%s rows=%s parsed=%s skipped_empty=%s headers=%s samples=%s",
            product_id,
            debug.get("section_found"),
            debug.get("table_found"),
            debug.get("row_total"),
            debug.get("row_parsed"),
            debug.get("row_skipped_empty"),
            debug.get("header_cells"),
            debug.get("sample_rows"),
        )


def _is_edit_url(page: DpPage) -> bool:
    url = str(page.url or "")
    return "goods_add" in url or "type=edit" in url


def _open_detail_page(page: DpPage, goods_id: str) -> tuple[bool, list[dict[str, Any]]]:
    steps: list[dict[str, Any]] = []
    goods_id = str(goods_id or "").strip()
    if not goods_id:
        steps.append({"step": "open_detail", "ok": False, "reason": "missing_goods_id"})
        return False, steps

    for template in GOODS_DETAIL_URLS:
        url = template.format(product_id=goods_id)
        steps.append({"step": "goto", "url": url})
        try:
            page.get(url)
            deadline = time.time() + 30
            while time.time() < deadline:
                if _is_edit_url(page):
                    steps.append({"step": "wait_ready", "ok": False, "reason": "landed_on_edit_url", "url": page.url})
                    break
                try:
                    ready = page.run_js(_WAIT_READ_READY_JS)
                    if ready:
                        steps.append({"step": "wait_ready", "ok": True, "url": page.url})
                        return True, steps
                except Exception as exc:
                    steps.append({"step": "wait_ready", "ok": False, "reason": str(exc)})
                time.sleep(0.6)
        except Exception as exc:
            steps.append({"step": "goto", "ok": False, "url": url, "error": str(exc)})

    steps.append({"step": "open_detail", "ok": False, "reason": "timeout_or_not_ready"})
    return False, steps


def _ensure_detail_page(page: DpPage, goods_id: str, steps: list[dict[str, Any]]) -> bool:
    if goods_id and _is_edit_url(page):
        steps.append({"step": "redirect_from_edit", "from_url": page.url})
        ok, sub = _open_detail_page(page, goods_id)
        steps.extend(sub)
        return ok
    try:
        if page.run_js(_WAIT_READ_READY_JS) and not _is_edit_url(page):
            steps.append({"step": "already_on_detail", "ok": True, "url": page.url})
            return True
    except Exception as exc:
        steps.append({"step": "already_on_detail", "ok": False, "error": str(exc)})
    ok, sub = _open_detail_page(page, goods_id)
    steps.extend(sub)
    return ok


def _scroll_to_spec_section(page: DpPage, steps: list[dict[str, Any]]) -> None:
    try:
        scrolled = page.run_js(_SCROLL_TO_SPEC_JS)
        steps.append({"step": "scroll_to_spec", "ok": bool(scrolled)})
    except Exception as exc:
        steps.append({"step": "scroll_to_spec", "ok": False, "error": str(exc)})
    time.sleep(1.2)


def _parse_spec_table(page: DpPage) -> dict[str, Any]:
    if _is_edit_url(page):
        return {"skus": [], "error": "edit_url_blocked", "debug": {"url": page.url}}
    try:
        result = page.run_js(_DIAGNOSE_AND_PARSE_JS)
        if isinstance(result, dict):
            return result
    except Exception as exc:
        logger.warning("parse spec section failed: %s", exc)
        return {"skus": [], "error": f"parse_exception:{exc}", "debug": {}}
    return {"skus": [], "error": "parse_failed", "debug": {}}


def scrape_spec_inventory(page: DpPage, *, pdd_product_id: str = "") -> dict[str, Any]:
    """只读抓取：款式、套餐/尺寸、拼单价、单买价、规格编码/商家编码。"""
    product_id = str(pdd_product_id or "").strip()
    steps: list[dict[str, Any]] = [{"step": "start", "product_id": product_id, "url": page.url}]

    if not _ensure_detail_page(page, product_id, steps):
        _log_debug(product_id, steps, None)
        return {
            "skus": [],
            "fields": list(_REQUIRED_FIELDS),
            "error": "detail_page_not_ready",
            "sku_count": 0,
            "scrape_source": "failed",
            "read_only": True,
            "scrape_steps": steps,
            "scrape_debug": steps[-1] if steps else {},
        }

    _scroll_to_spec_section(page, steps)
    parsed: dict[str, Any] = {"skus": [], "error": "spec_rows_empty", "debug": {}}
    attempt = 0
    deadline = time.time() + 30
    while time.time() < deadline:
        attempt += 1
        parsed = _parse_spec_table(page)
        debug = parsed.get("debug") if isinstance(parsed.get("debug"), dict) else {}
        steps.append({
            "step": "parse_attempt",
            "attempt": attempt,
            "error": parsed.get("error") or "",
            "sku_count": len(parsed.get("skus") or []),
            "debug": debug,
        })
        if parsed.get("skus"):
            break
        _scroll_to_spec_section(page, steps)
        time.sleep(0.8)

    skus = parsed.get("skus") if isinstance(parsed.get("skus"), list) else []
    debug = parsed.get("debug") if isinstance(parsed.get("debug"), dict) else {}
    normalized = normalize_pdd_lookup_skus(skus)
    error = "" if normalized else str(parsed.get("error") or "spec_rows_empty")

    _log_debug(product_id, steps, debug)

    return {
        "skus": normalized,
        "fields": list(_REQUIRED_FIELDS),
        "error": error,
        "sku_count": len(normalized),
        "scrape_source": "goods_detail_item",
        "read_only": True,
        "detail_url": str(page.url or ""),
        "scrape_steps": steps,
        "scrape_debug": debug,
        "spec_dim1_key": str(debug.get("spec_dim1_key") or "款式"),
        "spec_dim2_key": str(debug.get("spec_dim2_key") or "套餐"),
    }

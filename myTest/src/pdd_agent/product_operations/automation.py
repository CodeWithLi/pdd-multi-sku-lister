"""拼多多商品编辑页规格价格操作。"""

from __future__ import annotations

import re
import time
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.logging import get_logger
from pdd_agent.skills.delist.time_utils import extract_product_id_from_text
from pdd_agent.skills.listing.upload import (
    _click_goods_search,
    _fill_goods_merchant_code_filter,
    _open_goods_list,
    _reset_goods_list_filters,
)

logger = get_logger(__name__)

_EDIT_READY_JS = r"""
const body = (document.body?.innerText || '').replace(/\s+/g, ' ');
const url = String(location.href || '').toLowerCase();
return url.includes('goods_add') || url.includes('type=edit') || url.includes('/goods/edit')
    || (body.includes('基本信息') && body.includes('规格与库存') && body.includes('服务与承诺'));
"""

_PRICE_SECTION_READY_JS = r"""
const body = (document.body?.innerText || '').replace(/\s+/g, ' ');
const hasLabels = (body.includes('价格及库存') || body.includes('价格与库存'))
    && body.includes('拼单价') && (body.includes('规格编码') || body.includes('商家编码'));
if (!hasLabels) return false;
return Array.from(document.querySelectorAll('table')).some((table) => {
    const text = (table.innerText || '').replace(/\s+/g, ' ');
    return text.includes('拼单价') && (text.includes('规格编码') || text.includes('商家编码'));
}) && Array.from(document.querySelectorAll('table')).some(
    (table) => table.querySelectorAll('tbody tr input').length >= 2
);
"""

_SCROLL_TO_PRICE_SECTION_JS = r"""
function norm(v) { return String(v || '').replace(/\s+/g, ' ').trim(); }
for (const el of document.querySelectorAll('div, section, h1, h2, h3, label, span')) {
    const text = norm(el.innerText || el.textContent);
    if (text !== '价格及库存' && text !== '价格与库存') continue;
    el.scrollIntoView({ block: 'start', inline: 'nearest' });
    window.scrollBy(0, -100);
    return true;
}
window.scrollBy(0, Math.max(700, window.innerHeight * 0.8));
return false;
"""

_COLLECT_SKUS_JS = r"""
function norm(v) { return String(v || '').replace(/\s+/g, ' ').trim(); }
function visible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 3 && r.height > 3 && s.display !== 'none' && s.visibility !== 'hidden';
}
function findTables() {
    let headerTable = null;
    let dataTable = null;
    let dataScore = -1;
    for (const table of document.querySelectorAll('table')) {
        const text = norm(table.innerText);
        const inputs = table.querySelectorAll('tbody input').length;
        if (!headerTable && text.includes('拼单价') && (text.includes('规格编码') || text.includes('商家编码'))) {
            headerTable = table;
        }
        if (inputs > dataScore) { dataTable = table; dataScore = inputs; }
    }
    return { headerTable, dataTable: dataScore > 0 ? dataTable : null };
}
function headerInfo(table) {
    const cells = Array.from(table.querySelectorAll('thead tr:last-child th, thead tr:last-child td'));
    return cells.map((el) => ({ text: norm(el.innerText), rect: el.getBoundingClientRect() }));
}
function rangeFor(headers, names) {
    return headers.find((h) => names.some((name) => h.text.includes(name)))?.rect || null;
}
function cellAt(cells, range) {
    if (!range) return null;
    return cells.find((cell) => {
        const r = cell.getBoundingClientRect();
        const x = r.left + r.width / 2;
        return x >= range.left - 3 && x <= range.right + 3;
    }) || null;
}
const tables = findTables();
if (!tables.headerTable || !tables.dataTable) {
    return { skus: [], error: 'sku_table_not_found', at_bottom: true };
}
const headers = headerInfo(tables.headerTable);
const ranges = {
    style: rangeFor(headers, ['款式', '颜色']),
    package: rangeFor(headers, ['套餐', '尺寸', '型号']),
    inventory: rangeFor(headers, ['当前库存']),
    group: rangeFor(headers, ['拼单价']),
    single: rangeFor(headers, ['单买价']),
    code: rangeFor(headers, ['规格编码', '商家编码']),
    status: rangeFor(headers, ['状态']),
};
let currentStyle = '';
const skus = [];
for (const row of tables.dataTable.querySelectorAll('tbody tr')) {
    const cells = Array.from(row.querySelectorAll('td'));
    if (!cells.length) continue;
    const codeCell = cellAt(cells, ranges.code);
    const groupCell = cellAt(cells, ranges.group);
    const codeInput = codeCell?.querySelector('input');
    const groupInput = groupCell?.querySelector('input');
    const specCode = norm(codeInput?.value || codeCell?.innerText).replace(/\s+/g, '').toUpperCase();
    if (!specCode || !groupInput) continue;
    const style = norm(cellAt(cells, ranges.style)?.innerText);
    if (style) currentStyle = style;
    skus.push({
        style_name: style || currentStyle,
        package_name: norm(cellAt(cells, ranges.package)?.innerText),
        inventory: norm(cellAt(cells, ranges.inventory)?.innerText),
        group_price: norm(groupInput.value),
        single_price: norm(cellAt(cells, ranges.single)?.querySelector('input')?.value),
        spec_code: specCode,
        status: norm(cellAt(cells, ranges.status)?.innerText),
    });
}
let scroll = tables.dataTable.parentElement;
while (scroll && scroll !== document.body) {
    const style = getComputedStyle(scroll);
    if (scroll.scrollHeight > scroll.clientHeight + 10 && ['auto', 'scroll'].includes(style.overflowY)) break;
    scroll = scroll.parentElement;
}
const hasScroll = scroll && scroll !== document.body;
return {
    skus,
    error: skus.length ? '' : 'sku_rows_empty',
    at_bottom: !hasScroll || scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 4,
    scroll_top: hasScroll ? scroll.scrollTop : 0,
    scroll_height: hasScroll ? scroll.scrollHeight : 0,
    client_height: hasScroll ? scroll.clientHeight : 0,
};
"""

_SCROLL_SKU_TABLE_JS = r"""
const reset = Boolean(arguments[0]);
const candidates = Array.from(document.querySelectorAll('table'))
    .map((table) => ({ table, count: table.querySelectorAll('tbody input').length }))
    .sort((a, b) => b.count - a.count);
for (const item of candidates) {
    if (item.count <= 0) continue;
    const table = item.table;
    let scroll = table.parentElement;
    while (scroll && scroll !== document.body) {
        const style = getComputedStyle(scroll);
        if (scroll.scrollHeight > scroll.clientHeight + 10 && ['auto', 'scroll'].includes(style.overflowY)) break;
        scroll = scroll.parentElement;
    }
    if (!scroll || scroll === document.body) return { moved: false, at_bottom: true };
    scroll.scrollTop = reset ? 0 : Math.min(scroll.scrollHeight, scroll.scrollTop + Math.max(180, scroll.clientHeight * 0.8));
    scroll.dispatchEvent(new Event('scroll', { bubbles: true }));
    return { moved: true, at_bottom: scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 4 };
}
return { moved: false, at_bottom: true };
"""

_MARK_GROUP_PRICE_INPUT_JS = r"""
const target = String(arguments[0] || '').replace(/\s+/g, '').toUpperCase();
const token = String(arguments[1] || '');
function norm(v) { return String(v || '').replace(/\s+/g, ' ').trim(); }
function findTables() {
    const tables = Array.from(document.querySelectorAll('table'));
    const headerTable = tables.find((table) => {
        const text = norm(table.innerText);
        return text.includes('拼单价') && (text.includes('规格编码') || text.includes('商家编码'));
    }) || null;
    const dataTable = tables
        .map((table) => ({ table, count: table.querySelectorAll('tbody input').length }))
        .sort((a, b) => b.count - a.count)[0];
    return { headerTable, dataTable: dataTable && dataTable.count > 0 ? dataTable.table : null };
}
const tables = findTables();
if (!tables.headerTable || !tables.dataTable) return { found: false };
const headers = Array.from(tables.headerTable.querySelectorAll('thead tr:last-child th, thead tr:last-child td'))
    .map((el) => ({ text: norm(el.innerText), rect: el.getBoundingClientRect() }));
const groupRect = headers.find((h) => h.text.includes('拼单价'))?.rect;
const codeRect = headers.find((h) => h.text.includes('规格编码') || h.text.includes('商家编码'))?.rect;
if (!groupRect || !codeRect) return { found: false };
function cellAt(cells, range) {
    return cells.find((cell) => {
        const r = cell.getBoundingClientRect();
        const x = r.left + r.width / 2;
        return x >= range.left - 3 && x <= range.right + 3;
    }) || null;
}
for (const row of tables.dataTable.querySelectorAll('tbody tr')) {
    const cells = Array.from(row.querySelectorAll('td'));
    const codeCell = cellAt(cells, codeRect);
    const code = norm(codeCell?.querySelector('input')?.value || codeCell?.innerText)
        .replace(/\s+/g, '').toUpperCase();
    if (code !== target) continue;
    const input = cellAt(cells, groupRect)?.querySelector('input');
    if (!input) return { found: false };
    input.setAttribute('data-pdd-product-operation-token', token);
    input.scrollIntoView({ block: 'center', inline: 'nearest' });
    return { found: true, current: String(input.value || '') };
}
return { found: false };
"""


def normalize_code(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def normalize_price(value: Any) -> str:
    try:
        price = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"无效拼单价: {value}") from exc
    if price <= 0 or price > Decimal("999999.99"):
        raise ValueError(f"拼单价超出范围: {value}")
    return f"{price:.2f}"


def delist_product_by_code(
    page: DpPage,
    account_config: dict,
    *,
    product_code: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """复用精准下架操作；该店未发布目标编码时作为正常跳过。"""
    from pdd_agent.skills.delist.automation import process_single_product_delist

    result = process_single_product_delist(
        page,
        account_config,
        product_id="",
        merchant_code=str(product_code or "").strip(),
        dry_run=dry_run,
    )
    if result.get("error") == "product_id_not_found_on_sale":
        result.pop("error", None)
        result["status"] = "not_found"
        result["message"] = "该店未找到此商品编码，已跳过"
    return result


def validate_price_updates(current_skus: list[dict[str, Any]], updates: list[dict[str, Any]]) -> list[dict[str, str]]:
    available = {normalize_code(row.get("spec_code", "")) for row in current_skus}
    available.discard("")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in updates:
        code = normalize_code(row.get("spec_code", ""))
        if not code:
            raise ValueError("规格编码不能为空")
        if code in seen:
            raise ValueError(f"规格编码重复: {code}")
        if code not in available:
            raise ValueError(f"页面未找到规格编码: {code}")
        seen.add(code)
        normalized.append({"spec_code": code, "group_price": normalize_price(row.get("group_price"))})
    if not normalized:
        raise ValueError("至少需要修改一个规格")
    return normalized


def _row_product_code(row_text: str) -> str:
    match = re.search(r"商品编码\s*[：:]\s*([^\s\r\n]+)", str(row_text or ""))
    return str(match.group(1) if match else "").strip()


def _wait_exact_goods_row(page: DpPage, product_code: str, timeout: float = 20.0):
    expected = normalize_code(product_code)
    deadline = time.time() + timeout
    while time.time() < deadline:
        matches = []
        for row in page._page.locator("tbody tr").all():
            try:
                text = row.inner_text(timeout=500)
            except Exception:
                continue
            if normalize_code(_row_product_code(text)) == expected:
                matches.append((row, text))
        if matches:
            return matches
        time.sleep(0.5)
    return []


def _open_product_edit(page: DpPage, account_id: str, product_code: str) -> tuple[DpPage, dict[str, str]]:
    if not _open_goods_list(page, account_id, tab_text="在售中"):
        raise RuntimeError("无法打开在售商品列表，可能未登录")
    _reset_goods_list_filters(page)
    fill = _fill_goods_merchant_code_filter(page, product_code)
    if not fill.get("filled"):
        raise RuntimeError("无法填写商品编码搜索框")
    click = _click_goods_search(page)
    if not click.get("clicked"):
        raise RuntimeError("无法点击商品查询按钮")

    matches = _wait_exact_goods_row(page, product_code)
    if not matches:
        raise ValueError(f"在售列表未找到商品编码: {product_code}")
    if len(matches) > 1:
        ids = [extract_product_id_from_text(text) or "未知ID" for _, text in matches]
        raise ValueError(f"商品编码命中多条商品，请改用唯一编码: {', '.join(ids)}")

    row, row_text = matches[0]
    product_id = str(extract_product_id_from_text(row_text) or "").strip()
    title = ""
    try:
        title = str(row.locator(".goods-name").first.inner_text(timeout=500) or "").strip()
    except Exception:
        pass

    edit = row.locator('a[data-tracking-click-viewid="edit"]')
    if edit.count() != 1:
        edit = row.get_by_text("编辑", exact=True)
    if edit.count() != 1:
        raise RuntimeError("商品行未找到唯一编辑入口")
    edit.scroll_into_view_if_needed(timeout=3000)
    page._page.evaluate(
        """() => {
            window.__pddProductOperationEditUrl = '';
            window.__pddProductOperationOriginalOpen = window.open;
            window.open = (url) => {
                window.__pddProductOperationEditUrl = String(url || '');
                return null;
            };
        }"""
    )
    try:
        edit.click(force=True, timeout=5000)
        time.sleep(0.8)
        edit_url = str(
            page._page.evaluate("() => window.__pddProductOperationEditUrl || ''") or ""
        ).strip()
    finally:
        page._page.evaluate(
            """() => {
                if (window.__pddProductOperationOriginalOpen) {
                    window.open = window.__pddProductOperationOriginalOpen;
                }
                delete window.__pddProductOperationOriginalOpen;
            }"""
        )
    if not edit_url:
        raise RuntimeError("商品编辑按钮未生成编辑地址")

    active = page
    active.get(urljoin(str(page.url or ""), edit_url))
    try:
        active._page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass

    deadline = time.time() + 35
    while time.time() < deadline:
        ready = False
        try:
            ready = bool(active.run_js(_EDIT_READY_JS))
        except Exception:
            pass
        if ready:
            _open_price_section(active)
            return active, {"pdd_product_id": product_id, "title": title}
        time.sleep(0.6)
    raise RuntimeError(f"商品编辑页加载超时: {active.url}")


def _open_price_section(page: DpPage) -> None:
    """编辑页先落在基本信息；点击规格页签并滚动，触发价格表懒加载。"""
    tabs = page._page.get_by_text("规格与库存", exact=True)
    for index in range(tabs.count()):
        tab = tabs.nth(index)
        try:
            if tab.is_visible(timeout=300):
                tab.click(timeout=3000)
                time.sleep(0.8)
                break
        except Exception:
            continue

    deadline = time.time() + 35
    while time.time() < deadline:
        try:
            if page.run_js(_PRICE_SECTION_READY_JS):
                page.run_js(_SCROLL_TO_PRICE_SECTION_JS)
                time.sleep(0.6)
                return
            page.run_js(_SCROLL_TO_PRICE_SECTION_JS)
        except Exception:
            pass
        time.sleep(0.6)
    raise RuntimeError(f"商品编辑页价格及库存区域加载超时: {page.url}")


def _collect_all_skus(page: DpPage) -> list[dict[str, Any]]:
    page.run_js(_SCROLL_SKU_TABLE_JS, True)
    time.sleep(0.4)
    merged: dict[str, dict[str, Any]] = {}
    deadline = time.time() + 35
    while time.time() < deadline:
        result = page.run_js(_COLLECT_SKUS_JS)
        if isinstance(result, dict):
            for row in result.get("skus") or []:
                code = normalize_code(row.get("spec_code", ""))
                if code:
                    current = merged.get(code, {})
                    merged[code] = {
                        key: value if str(value or "").strip() else current.get(key, "")
                        for key, value in {**current, **row, "spec_code": code}.items()
                    }
            if merged and result.get("at_bottom"):
                break
        moved = page.run_js(_SCROLL_SKU_TABLE_JS, False)
        if not isinstance(moved, dict) or not moved.get("moved"):
            page.run_js(_SCROLL_TO_PRICE_SECTION_JS)
            time.sleep(0.6)
            continue
        time.sleep(0.3)
    page.run_js(_SCROLL_SKU_TABLE_JS, True)
    if not merged:
        raise RuntimeError("编辑页未读取到规格数据")
    return list(merged.values())


def read_product_price_specs(page: DpPage, account_id: str, product_code: str) -> dict[str, Any]:
    active, product = _open_product_edit(page, account_id, product_code)
    skus = _collect_all_skus(active)
    return {
        "status": "success",
        "account_id": account_id,
        "product_code": product_code,
        **product,
        "sku_count": len(skus),
        "skus": skus,
        "edit_url": str(active.url or ""),
    }


def _fill_group_price(page: DpPage, spec_code: str, price: str) -> str:
    page.run_js(_SCROLL_SKU_TABLE_JS, True)
    for _ in range(60):
        token = uuid.uuid4().hex
        marked = page.run_js(_MARK_GROUP_PRICE_INPUT_JS, spec_code, token)
        if isinstance(marked, dict) and marked.get("found"):
            locator = page._page.locator(f'[data-pdd-product-operation-token="{token}"]').first
            locator.fill(price, timeout=5000)
            locator.press("Tab", timeout=3000)
            current = str(locator.input_value(timeout=2000) or "").strip()
            if normalize_price(current) != price:
                raise RuntimeError(f"规格 {spec_code} 拼单价写入校验失败: {current}")
            return str(marked.get("current") or "")
        moved = page.run_js(_SCROLL_SKU_TABLE_JS, False)
        if not isinstance(moved, dict) or not moved.get("moved"):
            break
        time.sleep(0.25)
    raise ValueError(f"页面未找到规格编码: {spec_code}")


def _submit_edit(page: DpPage) -> None:
    buttons = page._page.get_by_role("button", name="提交", exact=True)
    submit = None
    for index in range(buttons.count() - 1, -1, -1):
        candidate = buttons.nth(index)
        try:
            if candidate.is_visible(timeout=300):
                submit = candidate
                break
        except Exception:
            continue
    if submit is None:
        raise RuntimeError("未找到商品编辑提交按钮")
    submit.click(timeout=5000)

    deadline = time.time() + 25
    confirm_words = ("确认提交", "确认修改", "确定")
    while time.time() < deadline:
        url = str(page.url or "").lower()
        if "goods_list" in url:
            return
        body = ""
        try:
            body = str(page._page.locator("body").inner_text(timeout=800) or "")
        except Exception:
            pass
        if any(word in body for word in ("修改成功", "编辑成功", "提交成功", "已提交审核")):
            return
        for word in confirm_words:
            try:
                button = page._page.get_by_role("button", name=word, exact=True).last
                if button.is_visible(timeout=200):
                    button.click(timeout=2000)
                    time.sleep(0.5)
                    break
            except Exception:
                continue
        time.sleep(0.5)
    raise RuntimeError("已点击提交，但未检测到修改成功结果")


def update_product_group_prices(
    page: DpPage,
    account_id: str,
    product_code: str,
    updates: list[dict[str, Any]],
    *,
    expected_product_id: str = "",
) -> dict[str, Any]:
    active, product = _open_product_edit(page, account_id, product_code)
    actual_product_id = str(product.get("pdd_product_id") or "")
    if expected_product_id and actual_product_id != expected_product_id:
        raise ValueError(f"商品ID不一致: 页面={actual_product_id}, 期望={expected_product_id}")

    current_skus = _collect_all_skus(active)
    normalized = validate_price_updates(current_skus, updates)
    applied = []
    for row in normalized:
        old_price = _fill_group_price(active, row["spec_code"], row["group_price"])
        applied.append({**row, "old_group_price": old_price})
    _submit_edit(active)
    logger.info(
        "[%s] product price updated product_code=%s product_id=%s specs=%s",
        account_id,
        product_code,
        actual_product_id,
        len(applied),
    )
    return {
        "status": "success",
        "account_id": account_id,
        "product_code": product_code,
        **product,
        "updated_count": len(applied),
        "updates": applied,
        "message": f"已修改 {len(applied)} 个规格的拼单价",
    }

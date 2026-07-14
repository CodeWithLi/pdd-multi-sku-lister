"""抖店 SKU 价格表填表：价格 / 现货库存 / 商家编码（对齐拼多多逻辑）。"""

from __future__ import annotations

import json
import time
from typing import Any

from playwright.sync_api import Page

from dy_agent.domain.models import ListingUnit, SkuCombo

# 抖店价格表 API：挂到 window.__dyPriceTableApi，避免 Playwright 跨 evaluate 丢函数。
_PRICE_TABLE_JS = r"""
() => {
  function norm(text) {
    return String(text || '')
      .replace(/\u00a0/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/（/g, '(')
      .replace(/）/g, ')')
      .replace(/＋/g, '+');
  }

  function normPrice(text) {
    const t = norm(text);
    if (!t) return '';
    const n = parseFloat(t.replace(/[^\d.+-]/g, ''));
    if (Number.isFinite(n)) return String(Math.round(n * 100) / 100);
    return t;
  }

  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  }

  function isEditableInput(inp) {
    if (!inp) return false;
    // Ant Design InputNumber 常带 readonly，仍可 focus 后写入，勿因 readonly 直接排除
    if (inp.disabled) return false;
    const t = String(inp.getAttribute('type') || inp.type || 'text').toLowerCase();
    if (['file', 'hidden', 'checkbox', 'radio', 'button', 'submit', 'image', 'reset'].includes(t)) {
      return false;
    }
    const ph = norm(inp.getAttribute('placeholder') || '');
    if (ph.includes('规格名称') || ph.includes('规格值') || ph.includes('关联的品牌')) return false;
    return true;
  }

  function cellInput(td) {
    if (!td) return null;
    const inputs = Array.from(td.querySelectorAll('input')).filter(isEditableInput);
    return inputs[0] || null;
  }

  function rowDataInputs(tr) {
    if (!tr) return [];
    const byTd = [];
    for (const td of tr.querySelectorAll('td')) {
      const inp = cellInput(td);
      if (inp) byTd.push(inp);
    }
    if (byTd.length >= 3) return byTd.slice(0, 6);
    const all = Array.from(tr.querySelectorAll('input')).filter(isEditableInput);
    return all.slice(0, 6);
  }

  function findSkuSectionRoot() {
    const markers = ['价格与库存', '现货库存', '商家编码', '批量设置'];
    const nodes = Array.from(document.querySelectorAll('div, section, form'));
    let best = null;
    let bestScore = 0;
    for (const el of nodes) {
      const text = norm(el.innerText || '').slice(0, 6000);
      let score = 0;
      for (const m of markers) if (text.includes(m)) score += 1;
      if (text.includes('价格') && text.includes('库存')) score += 1;
      if (score < 2) continue;
      // 优先包含 SKU 表头的较小容器
      if (text.includes('颜色分类') && text.includes('尺寸大小')) score += 2;
      const inputRows = Array.from(el.querySelectorAll('tr, [class*="table-row"], [class*="TableRow"]')).filter(
        (tr) => rowDataInputs(tr).length >= 2
      );
      score += Math.min(inputRows.length, 12);
      // 惩罚过大的容器（整页）
      if ((el.innerText || '').length > 20000) score -= 3;
      if (score > bestScore) {
        bestScore = score;
        best = el;
      }
    }
    return best;
  }

  function tableWrapper(table) {
    return (
      table?.closest('.ant-table, .ecom-g-table, [class*="sku-table"], [class*="SkuTable"], [class*="table-wrapper"]') ||
      table?.parentElement ||
      table
    );
  }

  function findSkuTable() {
    const root = findSkuSectionRoot() || document.body;
    // 优先有数据行的表；仅有表头的固定列表靠后
    const tables = Array.from(root.querySelectorAll('table'));
    let best = null;
    let bestScore = -1;
    for (const table of tables) {
      const wrap = tableWrapper(table);
      const text = norm((wrap || table).innerText || '');
      let score = 0;
      if (text.includes('价格')) score += 2;
      if (text.includes('库存')) score += 2;
      if (text.includes('商家编码') || text.includes('货号')) score += 2;
      if (text.includes('颜色分类') || text.includes('尺寸')) score += 1;
      const dataRows = Array.from(
        (wrap || table).querySelectorAll('tbody tr, .ant-table-tbody > tr, .ecom-g-table-tbody > tr, tr')
      ).filter((tr) => rowDataInputs(tr).length >= 2 && !isBatchSettingRow(tr));
      score += dataRows.length * 5;
      if (dataRows.length === 0 && text.includes('颜色分类') && text.includes('价格')) {
        // 只有表头：记录下来作回退，但分数低
        score += 1;
      }
      if (score > bestScore) {
        bestScore = score;
        best = table;
      }
    }
    if (best) return best;
    for (const table of document.querySelectorAll('table')) {
      if (Array.from(table.querySelectorAll('tr')).some((tr) => rowDataInputs(tr).length >= 2)) {
        return table;
      }
    }
    return null;
  }

  function isBatchSettingRow(tr) {
    const t = norm(tr.innerText || '');
    if (t.includes('批量设置')) return true;
    if (t.includes('全部颜色') || t.includes('全部尺寸')) return true;
    return false;
  }

  function headerTexts(table) {
    const headers = [];
    const root = table?.closest('[class*="table"], [class*="Table"], .ant-table, .ecom-g-table') || table?.parentElement || table;
    const theadCells = root
      ? root.querySelectorAll(
          'thead th, thead td, .ant-table-thead th, .ecom-g-table-thead th, [class*="table-header"] th'
        )
      : [];
    if (theadCells.length) {
      theadCells.forEach((th) => headers.push(norm(th.innerText || th.textContent || '')));
      if (headers.some(Boolean)) return headers;
    }
    const ths = table.querySelectorAll('thead th, thead td, tr th');
    if (ths.length) {
      ths.forEach((th) => headers.push(norm(th.innerText || th.textContent || '')));
      return headers;
    }
    const firstRow = table.querySelector('tr');
    if (!firstRow) return headers;
    firstRow.querySelectorAll('th, td').forEach((cell) => {
      headers.push(norm(cell.innerText || cell.textContent || ''));
    });
    return headers;
  }

  function colIndex(headers, patterns) {
    for (let i = 0; i < headers.length; i++) {
      const h = headers[i];
      for (const p of patterns) {
        if (h === p || h.startsWith(p) || (p.length >= 2 && h.includes(p))) return i;
      }
    }
    return -1;
  }

  function buildColumnMap(table) {
    const headers = headerTexts(table);
    return {
      color: colIndex(headers, ['颜色分类', '颜色']),
      size: colIndex(headers, ['尺寸大小', '尺寸']),
      price: colIndex(headers, ['价格', '售价', '销售价']),
      inventory: colIndex(headers, ['现货库存', '库存']),
      merchant: colIndex(headers, ['商家编码', '货号', 'SKU编码']),
      headers,
    };
  }

  function reactFill(input, value) {
    if (!input) return false;
    const val = String(value ?? '');
    try { input.focus({ preventScroll: true }); } catch (e) { try { input.focus(); } catch (e2) {} }
    try { input.select(); } catch (e) {}
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    if (setter) {
      setter.call(input, '');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      setter.call(input, val);
    } else {
      input.value = val;
    }
    input.dispatchEvent(new InputEvent('input', { bubbles: true, data: val, inputType: 'insertText' }));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Enter' }));
    input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Enter' }));
    try { input.blur(); } catch (e) {}
    const got = norm(input.value);
    return got === norm(val) || normPrice(got) === normPrice(val);
  }

  function readInput(input) {
    return input ? norm(input.value) : '';
  }

  function labelEquals(a, b) {
    const x = norm(a);
    const y = norm(b);
    if (!x || !y) return false;
    return x === y || x.includes(y) || y.includes(x);
  }

  function parseRows(table, colMap, styleNames, sizeNames) {
    const styleSet = new Set((styleNames || []).map(norm));
    const sizeSet = new Set((sizeNames || []).map(norm));
    const rows = [];
    let carryColor = '';
    const root = findSkuSectionRoot() || tableWrapper(table) || table || document.body;
    const seen = new Set();
    const trList = [];

    function pushTr(tr) {
      if (!tr || seen.has(tr)) return;
      if (isBatchSettingRow(tr)) return;
      // 虚拟滚动行可能暂时不可见，仍要纳入
      if (rowDataInputs(tr).length < 2) return;
      seen.add(tr);
      trList.push(tr);
    }

    if (table) {
      const wrap = tableWrapper(table);
      (wrap || table)
        .querySelectorAll('tbody tr, .ant-table-tbody > tr, .ecom-g-table-tbody > tr, tr')
        .forEach(pushTr);
    }
    root
      .querySelectorAll(
        'table tbody tr, .ant-table-tbody > tr, .ecom-g-table-tbody > tr, [class*="table-body"] tr, [class*="sku"] tr'
      )
      .forEach(pushTr);

    for (const tr of trList) {
      const tds = Array.from(tr.querySelectorAll('td'));
      const labels = [];
      for (const td of tds) {
        if (cellInput(td)) break;
        let t = norm(td.innerText || td.textContent || '');
        // 去掉「已选/删除」等操作文案干扰
        t = t.replace(/删除|编辑|上传|预览图/g, '').trim();
        if (t) labels.push(t);
      }

      let color = carryColor;
      let size = '';
      if (labels.length >= 2) {
        color = labels[0];
        size = labels[1];
        carryColor = color;
      } else if (labels.length === 1) {
        const token = labels[0];
        if ([...styleSet].some((s) => labelEquals(token, s)) && ![...sizeSet].some((s) => labelEquals(token, s))) {
          color = token;
          carryColor = token;
        } else {
          size = token;
        }
      }

      if (colMap && colMap.color >= 0 && tds[colMap.color]) {
        const ctd = tds[colMap.color];
        const ct = norm(ctd.innerText || ctd.textContent || '');
        if (ct && !cellInput(ctd)) {
          color = ct;
          carryColor = ct;
        }
      }
      if (colMap && colMap.size >= 0 && tds[colMap.size]) {
        const std = tds[colMap.size];
        const st = norm(std.innerText || std.textContent || '');
        if (st && !cellInput(std)) size = st;
      }

      // rowspan：颜色格空白时沿用上一行
      if (!size && labels.length === 0 && carryColor) {
        // 可能整行只有输入框（fixed 列分离），仍保留
      }

      rows.push({
        tr,
        color: norm(color),
        size: norm(size),
        inputCount: rowDataInputs(tr).length,
      });
      if (color) carryColor = color;
    }
    return rows;
  }

  function findRow(table, colMap, styleNames, sizeNames, style, size) {
    const targetStyle = norm(style);
    const targetSize = norm(size);
    const parsed = parseRows(table, colMap, styleNames, sizeNames);
    for (const row of parsed) {
      if (labelEquals(row.color, targetStyle) && labelEquals(row.size, targetSize)) return row.tr;
    }
    for (const row of parsed) {
      if (labelEquals(row.size, targetSize) && (!targetStyle || labelEquals(row.color, targetStyle))) {
        return row.tr;
      }
    }
    return null;
  }

  function findRowByIndex(table, colMap, styleNames, sizeNames, index) {
    const parsed = parseRows(table, colMap, styleNames, sizeNames);
    if (index < 0 || index >= parsed.length) return null;
    return parsed[index].tr;
  }

  function matrixIndex(style, size, styleNames, sizeNames) {
    const si = (styleNames || []).findIndex((x) => labelEquals(x, style));
    const mi = (sizeNames || []).findIndex((x) => labelEquals(x, size));
    if (si < 0 || mi < 0) return -1;
    return si * (sizeNames || []).length + mi;
  }

  function scrollContainer(table) {
    const candidates = [];
    const start = table || findSkuSectionRoot() || document.body;
    let el = start;
    while (el && el !== document.documentElement) {
      const st = getComputedStyle(el);
      const oy = st.overflowY || st.overflow;
      if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay') && el.scrollHeight > el.clientHeight + 4) {
        candidates.push(el);
      }
      el = el.parentElement;
    }
    return candidates[0] || table?.parentElement || table || document.scrollingElement;
  }

  function scrollFindRow(table, colMap, styleNames, sizeNames, style, size, rowIndex) {
    const container = scrollContainer(table);
    let tr = findRow(table, colMap, styleNames, sizeNames, style, size);
    if (!tr && Number.isFinite(rowIndex) && rowIndex >= 0) {
      tr = findRowByIndex(table, colMap, styleNames, sizeNames, rowIndex);
    }
    if (!tr) {
      const mi = matrixIndex(style, size, styleNames, sizeNames);
      if (mi >= 0) tr = findRowByIndex(table, colMap, styleNames, sizeNames, mi);
    }
    if (tr) {
      try { tr.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }); } catch (e) {}
      return tr;
    }
    const maxSteps = 40;
    for (let i = 0; i < maxSteps; i++) {
      try {
        container.scrollTop = (container.scrollTop || 0) + Math.max(80, (container.clientHeight || 240) * 0.5);
      } catch (e) {}
      tr = findRow(table, colMap, styleNames, sizeNames, style, size);
      if (!tr && Number.isFinite(rowIndex) && rowIndex >= 0) {
        tr = findRowByIndex(table, colMap, styleNames, sizeNames, rowIndex);
      }
      if (tr) {
        try { tr.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }); } catch (e) {}
        return tr;
      }
    }
    try { container.scrollTop = 0; } catch (e) {}
    tr = findRow(table, colMap, styleNames, sizeNames, style, size);
    if (!tr && Number.isFinite(rowIndex) && rowIndex >= 0) {
      tr = findRowByIndex(table, colMap, styleNames, sizeNames, rowIndex);
    }
    return tr;
  }

  function resolveFieldInputs(tr, colMap) {
    const tds = Array.from(tr.querySelectorAll('td'));
    const byCol = {
      price: colMap.price >= 0 ? cellInput(tds[colMap.price]) : null,
      inventory: colMap.inventory >= 0 ? cellInput(tds[colMap.inventory]) : null,
      merchant: colMap.merchant >= 0 ? cellInput(tds[colMap.merchant]) : null,
    };
    if (byCol.price && byCol.inventory && byCol.merchant) return byCol;

    // 回退：按行内可编辑 input 顺序 = 价格 / 现货库存 / 商家编码（抖店常见）
    const inputs = rowDataInputs(tr);
    const out = {
      price: byCol.price || inputs[0] || null,
      inventory: byCol.inventory || inputs[1] || null,
      merchant: byCol.merchant || inputs[2] || null,
    };
    // 若列映射把某列错指到非输入格，再按顺序补齐未分配的 inputs
    if (!out.price || !out.inventory || !out.merchant) {
      const used = new Set([out.price, out.inventory, out.merchant].filter(Boolean));
      const rest = inputs.filter((x) => !used.has(x));
      if (!out.price) out.price = rest.shift() || null;
      if (!out.inventory) out.inventory = rest.shift() || null;
      if (!out.merchant) out.merchant = rest.shift() || null;
    }
    return out;
  }

  function fillRow(table, colMap, tr, values) {
    if (!tr) return { ok: false, reason: 'row_not_found' };
    try { tr.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }); } catch (e) {}
    const fields = resolveFieldInputs(tr, colMap);
    const results = {
      price: reactFill(fields.price, values.price),
      inventory: reactFill(fields.inventory, values.inventory),
      merchant_code: reactFill(fields.merchant, values.merchant_code),
    };
    const ok = Object.values(results).every(Boolean);
    return {
      ok,
      results,
      inputCount: rowDataInputs(tr).length,
      hasPrice: !!fields.price,
      hasInventory: !!fields.inventory,
      hasMerchant: !!fields.merchant,
    };
  }

  function readRow(table, colMap, tr) {
    const fields = resolveFieldInputs(tr, colMap);
    return {
      price: readInput(fields.price),
      inventory: readInput(fields.inventory),
      merchant_code: readInput(fields.merchant),
    };
  }

  function verifyRow(expected, actual) {
    const issues = [];
    if (normPrice(actual.price) !== normPrice(expected.price)) issues.push('price');
    if (norm(actual.inventory) !== norm(expected.inventory)) issues.push('inventory');
    if (norm(actual.merchant_code).toUpperCase() !== norm(expected.merchant_code).toUpperCase()) {
      issues.push('merchant_code');
    }
    return { ok: issues.length === 0, issues };
  }

  function findRowByMerchantCode(table, colMap, merchantCode) {
    const target = norm(merchantCode).toUpperCase();
    if (!target) return null;
    const parsed = parseRows(table, colMap, [], []);
    for (const row of parsed) {
      const fields = resolveFieldInputs(row.tr, colMap);
      const val = readInput(fields.merchant);
      if (norm(val).toUpperCase() === target) {
        return { ...row, color: row.color, size: row.size };
      }
    }
    return null;
  }

  function countCandidateRows() {
    const root = findSkuSectionRoot() || document.body;
    const allTr = Array.from(
      root.querySelectorAll('tr, [class*="table-row"], [class*="TableRow"]')
    );
    let withInputs = 0;
    let totalInputs = 0;
    for (const tr of allTr) {
      if (isBatchSettingRow(tr)) continue;
      const n = rowDataInputs(tr).length;
      totalInputs += n;
      if (n >= 2) withInputs += 1;
    }
    return { trTotal: allTr.length, rowsWithInputs: withInputs, inputHits: totalInputs };
  }

  function scrollPriceSectionIntoView() {
    const nodes = Array.from(document.querySelectorAll('div, section, h3, h4, span'));
    const hit = nodes.find((el) => {
      const t = norm(el.innerText || '');
      return t.startsWith('价格与库存') || (t.includes('价格与库存') && t.includes('价格填写进度'));
    });
    if (hit) {
      try { hit.scrollIntoView({ block: 'start', behavior: 'instant' }); } catch (e) {}
    }
    try { window.scrollBy(0, 240); } catch (e) {}
    return !!hit;
  }

  function diagnose(styleNames, sizeNames) {
    const table = findSkuTable();
    const colMap = table ? buildColumnMap(table) : null;
    const parsed = table ? parseRows(table, colMap, styleNames || [], sizeNames || []) : [];
    const candidates = countCandidateRows();
    return {
      tableFound: !!table,
      sectionFound: !!findSkuSectionRoot(),
      headers: colMap ? colMap.headers : [],
      colMap: colMap
        ? {
            color: colMap.color,
            size: colMap.size,
            price: colMap.price,
            inventory: colMap.inventory,
            merchant: colMap.merchant,
          }
        : null,
      rowCount: parsed.length,
      rows: parsed.slice(0, 12).map((r, i) => ({
        i,
        color: r.color,
        size: r.size,
        inputCount: r.inputCount,
      })),
      candidates,
      styleNames: styleNames || [],
      sizeNames: sizeNames || [],
    };
  }

  // 必须挂 window：Playwright 无法跨 evaluate 传递函数对象
  window.__dyPriceTableApi = {
    norm,
    normPrice,
    findSkuTable,
    buildColumnMap,
    scrollFindRow,
    fillRow,
    readRow,
    verifyRow,
    findRowByMerchantCode,
    parseRows,
    diagnose,
    matrixIndex,
    scrollPriceSectionIntoView,
    countCandidateRows,
  };
  return true;
}
"""


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _row_data_from_sku(sku: SkuCombo, defaults: dict[str, str] | None = None) -> dict[str, str]:
    defaults = defaults or {}
    return {
        "price": str(getattr(sku, "price", None) or defaults.get("price") or defaults.get("group_price") or "199.9"),
        "inventory": str(getattr(sku, "inventory", None) or defaults.get("inventory") or "10"),
        "merchant_code": str(getattr(sku, "combo_folder", "") or ""),
    }


def _find_duplicate_spec_pairs(skus: list[SkuCombo]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    dupes: list[dict[str, str]] = []
    for sku in skus:
        key = (str(sku.style_name or "").strip(), str(sku.model_name or "").strip())
        if key in seen:
            dupes.append(
                {
                    "style": key[0],
                    "size": key[1],
                    "combo_folder": str(sku.combo_folder or ""),
                    "reason": "duplicate_spec_pair",
                }
            )
        seen.add(key)
    return dupes


def _ensure_price_table_api(page: Page) -> None:
    ok = page.evaluate(_PRICE_TABLE_JS)
    installed = page.evaluate("() => !!(window.__dyPriceTableApi && window.__dyPriceTableApi.findSkuTable)")
    if not ok or not installed:
        raise RuntimeError("抖店价格表 JS API 注入失败（window.__dyPriceTableApi 未就绪）")


def ensure_price_table_rows_ready(
    page: Page,
    account_id: str,
    listing_label: str,
    *,
    expected: int,
    style_names: list[str],
    size_names: list[str],
    max_wait: int = 45,
) -> dict[str, Any]:
    """切到「价格库存」并滚动到「价格与库存」，等待 SKU 明细行渲染。"""
    from dy_agent.skills.listing.publish_price_stock import click_price_stock_tab

    target = max(1, expected)
    clicked = click_price_stock_tab(page, account_id, listing_label)
    _log(
        account_id,
        listing_label,
        f"Step5 准备价格表：价格库存 tab={'已点' if clicked else '未点到'}，期望 {target} 行",
    )

    _ensure_price_table_api(page)
    last: dict[str, Any] = {}
    for sec in range(max_wait):
        try:
            page.evaluate(
                """
                () => {
                  const api = window.__dyPriceTableApi;
                  if (api && api.scrollPriceSectionIntoView) api.scrollPriceSectionIntoView();
                  try { window.scrollBy(0, 180); } catch (e) {}
                }
                """
            )
        except Exception:
            pass

        last = _diagnose_price_table(page, style_names=style_names, size_names=size_names)
        row_count = int(last.get("rowCount") or 0)
        cand = (last.get("candidates") or {}) if isinstance(last.get("candidates"), dict) else {}
        with_inputs = int(cand.get("rowsWithInputs") or 0)
        best = max(row_count, with_inputs)
        if best >= target:
            _log(
                account_id,
                listing_label,
                f"价格表 SKU 行就绪: rowCount={row_count} rowsWithInputs={with_inputs}",
            )
            return last
        if sec == 0 or (sec + 1) % 5 == 0:
            _log(
                account_id,
                listing_label,
                f"等待价格表 SKU 行… ({best}/{target}) ({sec + 1}/{max_wait}s) "
                f"diag={json.dumps(last, ensure_ascii=False)}",
            )
        time.sleep(1)

    raise RuntimeError(
        f"[{account_id}] [{listing_label}] 价格与库存 SKU 明细行未出现"
        f"（期望 {target} 行）。当前诊断: {json.dumps(last, ensure_ascii=False)}"
    )


def _diagnose_price_table(
    page: Page,
    *,
    style_names: list[str],
    size_names: list[str],
) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """
            ([styleNames, sizeNames]) => {
              const api = window.__dyPriceTableApi;
              if (!api || !api.diagnose) return { tableFound: false, reason: 'api_not_installed' };
              return api.diagnose(styleNames, sizeNames);
            }
            """,
            [style_names, size_names],
        )
        return raw if isinstance(raw, dict) else {"raw": raw}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _matrix_row_index(style: str, size: str, style_names: list[str], size_names: list[str]) -> int:
    try:
        si = next(i for i, n in enumerate(style_names) if str(n).strip() == str(style).strip())
        mi = next(i for i, n in enumerate(size_names) if str(n).strip() == str(size).strip())
    except StopIteration:
        return -1
    return si * len(size_names) + mi


def _fill_one_sku_row(
    page: Page,
    *,
    style_name: str,
    size_name: str,
    row_data: dict[str, str],
    style_names: list[str],
    size_names: list[str],
    row_index: int = -1,
    max_retries: int = 4,
) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "reason": "fill_failed"}
    for _attempt in range(max_retries):
        result = page.evaluate(
            """
            ([style, size, rowData, styleNames, sizeNames, rowIndex]) => {
              const api = window.__dyPriceTableApi;
              if (!api) return { ok: false, reason: 'api_not_installed' };
              const table = api.findSkuTable();
              if (!table) return { ok: false, reason: 'table_not_found' };
              const colMap = api.buildColumnMap(table);
              const tr = api.scrollFindRow(
                table, colMap, styleNames, sizeNames, style, size, rowIndex
              );
              if (!tr) {
                return {
                  ok: false,
                  reason: 'row_not_found',
                  expected: { style, size, rowIndex },
                  colMap: {
                    price: colMap.price,
                    inventory: colMap.inventory,
                    merchant: colMap.merchant,
                    headers: colMap.headers,
                  },
                };
              }
              const fill = api.fillRow(table, colMap, tr, rowData);
              if (!fill.ok) {
                return {
                  ok: false,
                  reason: 'fill_failed',
                  fill,
                  actual: api.readRow(table, colMap, tr),
                };
              }
              const actual = api.readRow(table, colMap, tr);
              const verify = api.verifyRow(rowData, actual);
              return {
                ok: verify.ok,
                reason: verify.ok ? 'ok' : 'verify_failed',
                issues: verify.issues,
                actual,
                expected: rowData,
              };
            }
            """,
            [style_name, size_name, row_data, style_names, size_names, row_index],
        )
        if isinstance(result, dict) and result.get("ok"):
            return result
        time.sleep(0.35)
    return result if isinstance(result, dict) else {"ok": False, "reason": "fill_failed"}


def _reverse_verify_merchant_code(
    page: Page,
    *,
    sku: SkuCombo,
    style_names: list[str],
    size_names: list[str],
) -> dict[str, Any]:
    return page.evaluate(
        """
        ([combo, style, size, styleNames, sizeNames]) => {
          const api = window.__dyPriceTableApi;
          if (!api) return { ok: false, reason: 'api_not_installed' };
          const table = api.findSkuTable();
          if (!table) return { ok: false, reason: 'table_not_found' };
          const colMap = api.buildColumnMap(table);
          const row = api.findRowByMerchantCode(table, colMap, combo);
          if (!row) return { ok: false, reason: 'spec_code_not_on_page', combo_folder: combo };
          if (api.norm(row.color) && api.norm(style) && api.norm(row.color) !== api.norm(style)
              && !(String(row.color).includes(String(style)) || String(style).includes(String(row.color)))) {
            return {
              ok: false,
              reason: 'reverse_style_mismatch',
              expected_style: style,
              actual_style: row.color,
              combo_folder: combo,
            };
          }
          if (api.norm(row.size) && api.norm(size) && api.norm(row.size) !== api.norm(size)
              && !(String(row.size).includes(String(size)) || String(size).includes(String(row.size)))) {
            return {
              ok: false,
              reason: 'reverse_size_mismatch',
              expected_size: size,
              actual_size: row.size,
              combo_folder: combo,
            };
          }
          return { ok: true };
        }
        """,
        [
            str(sku.combo_folder or ""),
            str(sku.style_name or ""),
            str(sku.model_name or ""),
            style_names,
            size_names,
        ],
    )


def fill_sku_price_table(
    page: Page,
    account_id: str,
    listing_label: str,
    skus: list[SkuCombo],
    *,
    style_names: list[str],
    size_names: list[str],
    defaults: dict[str, str] | None = None,
) -> dict[str, Any]:
    """批量按「颜色分类 + 尺寸大小」逐行填写价格/库存/商家编码。"""
    _ensure_price_table_api(page)
    filled = 0
    failed: list[dict[str, Any]] = []
    total = len(skus)

    for idx, sku in enumerate(skus):
        row_data = _row_data_from_sku(sku, defaults)
        row_index = _matrix_row_index(
            str(sku.style_name or ""),
            str(sku.model_name or ""),
            style_names,
            size_names,
        )
        if row_index < 0:
            row_index = idx
        result = _fill_one_sku_row(
            page,
            style_name=str(sku.style_name or ""),
            size_name=str(sku.model_name or ""),
            row_data=row_data,
            style_names=style_names,
            size_names=size_names,
            row_index=row_index,
        )
        if result.get("ok"):
            filled += 1
            _log(
                account_id,
                listing_label,
                f"价格表 ({idx + 1}/{total}) {sku.style_name}/{sku.model_name} "
                f"价={row_data['price']} 库存={row_data['inventory']} 编码={row_data['merchant_code']}",
            )
        else:
            failed.append(
                {
                    "style": sku.style_name,
                    "size": sku.model_name,
                    "combo_folder": sku.combo_folder,
                    "reason": str(result.get("reason") or "fill_failed"),
                    "detail": str(result.get("issues") or result.get("fill") or result.get("actual") or ""),
                }
            )
            _log(
                account_id,
                listing_label,
                f"价格表失败 ({idx + 1}/{total}) {sku.style_name}/{sku.model_name}: {result}",
            )
        time.sleep(0.08)

    return {
        "price_filled": filled,
        "price_total": total,
        "failed_items": failed,
        "verify_passed": not failed,
        "spec_fill_verify_mode": False,
    }


def fill_sku_price_table_verified(
    page: Page,
    account_id: str,
    listing_label: str,
    skus: list[SkuCombo],
    *,
    style_names: list[str],
    size_names: list[str],
    defaults: dict[str, str] | None = None,
) -> dict[str, Any]:
    """规格填表校验：逐 SKU 填写 → 正向校验 → 商家编码反查对齐。"""
    dupes = _find_duplicate_spec_pairs(skus)
    if dupes:
        return {
            "price_filled": 0,
            "price_total": len(skus),
            "failed_items": dupes,
            "verify_issues": dupes,
            "duplicate_spec_pairs": dupes,
            "verify_passed": False,
            "verify_passed_count": 0,
            "verify_total": len(skus),
            "spec_fill_verify_mode": True,
        }

    _ensure_price_table_api(page)
    diag = _diagnose_price_table(page, style_names=style_names, size_names=size_names)
    _log(account_id, listing_label, f"价格表诊断: {json.dumps(diag, ensure_ascii=False)}")

    filled = 0
    failed: list[dict[str, Any]] = []
    verify_issues: list[dict[str, Any]] = []
    total = len(skus)

    for idx, sku in enumerate(skus):
        row_data = _row_data_from_sku(sku, defaults)
        row_index = _matrix_row_index(
            str(sku.style_name or ""),
            str(sku.model_name or ""),
            style_names,
            size_names,
        )
        if row_index < 0:
            row_index = idx
        result = _fill_one_sku_row(
            page,
            style_name=str(sku.style_name or ""),
            size_name=str(sku.model_name or ""),
            row_data=row_data,
            style_names=style_names,
            size_names=size_names,
            row_index=row_index,
            max_retries=5,
        )
        if not result.get("ok"):
            detail = (
                result.get("issues")
                or result.get("fill")
                or result.get("actual")
                or result.get("expected")
                or result.get("reason")
                or ""
            )
            item = {
                "style": sku.style_name,
                "size": sku.model_name,
                "combo_folder": sku.combo_folder,
                "reason": str(result.get("reason") or "forward_verify_failed"),
                "detail": str(detail),
            }
            failed.append(item)
            verify_issues.append(item)
            _log(
                account_id,
                listing_label,
                f"规格校验失败 ({idx + 1}/{total}) {sku.style_name}/{sku.model_name}: {result}",
            )
            continue

        reverse = _reverse_verify_merchant_code(
            page,
            sku=sku,
            style_names=style_names,
            size_names=size_names,
        )
        if not reverse.get("ok"):
            item = {
                "style": sku.style_name,
                "size": sku.model_name,
                "combo_folder": sku.combo_folder,
                "reason": str(reverse.get("reason") or "verify_failed"),
                "detail": str(reverse.get("actual_style") or reverse.get("actual_size") or ""),
            }
            failed.append(item)
            verify_issues.append(item)
            _log(
                account_id,
                listing_label,
                f"规格反查失败 ({idx + 1}/{total}) {sku.style_name}/{sku.model_name}: {reverse}",
            )
            continue

        filled += 1
        _log(
            account_id,
            listing_label,
            f"规格校验 ({idx + 1}/{total}) ✓ {sku.style_name}/{sku.model_name} → {sku.combo_folder}",
        )
        time.sleep(0.1)

    if failed:
        diag2 = _diagnose_price_table(page, style_names=style_names, size_names=size_names)
        _log(account_id, listing_label, f"价格表失败后诊断: {json.dumps(diag2, ensure_ascii=False)}")

    passed = filled == total and not failed
    return {
        "price_filled": filled,
        "price_total": total,
        "failed_items": failed,
        "verify_issues": verify_issues,
        "verify_passed": passed,
        "verify_passed_count": filled,
        "verify_total": total,
        "duplicate_spec_pairs": dupes,
        "spec_fill_verify_mode": True,
        "price_table_diagnose": diag,
    }


def fill_unit_price_table(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    *,
    style_names: list[str],
    size_names: list[str],
    defaults: dict[str, str] | None = None,
    verify: bool = False,
) -> dict[str, Any]:
    if verify:
        return fill_sku_price_table_verified(
            page,
            account_id,
            unit.listing_label,
            list(unit.skus),
            style_names=style_names,
            size_names=size_names,
            defaults=defaults,
        )
    return fill_sku_price_table(
        page,
        account_id,
        unit.listing_label,
        list(unit.skus),
        style_names=style_names,
        size_names=size_names,
        defaults=defaults,
    )

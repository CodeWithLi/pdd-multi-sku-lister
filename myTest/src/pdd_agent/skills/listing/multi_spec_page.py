"""多规格（款式 + 型号）拼多多页面填写。"""
import json
import time

from pdd_agent.skills.listing import _sku_table_debug as sku_dbg


def _now() -> float:
    return time.perf_counter()


def _log_step(account_id: str, step: str, started: float):
    print(f"[{account_id}] [耗时 {time.perf_counter() - started:.2f}s] {step}", flush=True)


def _safe_exc(exc: BaseException, limit: int = 300) -> str:
    msg = str(exc)
    if len(msg) > limit:
        msg = msg[:limit] + "..."
    return msg.encode("utf-8", errors="replace").decode("utf-8")


def _click_blank_area(page):
    """点击空白/价格表区域，让规格录入生效并激活下方输入框。"""
    page.run_js(
        """
        for (const el of document.querySelectorAll('span,div,label,p')) {
            const t = (el.textContent || '').trim();
            if (t === '价格及库存' || t === '价格与库存') {
                el.click();
                return;
            }
        }
        const sku = document.querySelector('.sku-table, .sku-list');
        if (sku) { sku.click(); return; }
        document.body.click();
        """
    )
    time.sleep(0.3)


def _spec_row_boxes(page):
    container = page.ele("#spec", timeout=3)
    if not container:
        return container, []
    boxes = container.eles("css:.goods-spec-row-box")
    return container, boxes


def _inputs_in_box(box):
    return box.eles("tag:input@placeholder=请输入规格名称") if box else []


def _wait_inputs_count(box, count: int, account_id: str, label: str, max_wait: int = 25) -> bool:
    for attempt in range(max_wait):
        cur = len(_inputs_in_box(box))
        if cur >= count:
            return True
        print(f"[{account_id}] 等待{label}规格框 ({cur}/{count}) ({attempt + 1}/{max_wait})")
        time.sleep(0.5)
    return False


def _react_fill_spec_input(page, inp, value: str) -> bool:
    """规格名输入：触发 React input/change/Enter，避免「框里有字但未生效」。"""
    try:
        return bool(
            page.run_js(
                """
                const el = arguments[0];
                const val = String(arguments[1] || '').trim();
                if (!el || !val) return false;
                try { el.focus(); } catch (e) {}
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                )?.set;
                if (setter) setter.call(el, val);
                else el.value = val;
                el.dispatchEvent(new InputEvent('input', {
                    bubbles: true, data: val, inputType: 'insertText'
                }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
                }));
                el.dispatchEvent(new KeyboardEvent('keyup', {
                    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
                }));
                try { el.blur(); } catch (e) {}
                return (el.value || '').trim() === val;
                """,
                inp,
                value,
            )
        )
    except Exception:
        return False


def _add_values_to_spec_box(page, box, account_id: str, label: str, names: list[str]):
    """向单个规格维度（款式或型号）逐个录入名称。"""
    if not names:
        return

    for i, name in enumerate(names):
        if i > 0:
            _wait_inputs_count(box, i + 1, account_id, label)

        inputs = _inputs_in_box(box)
        if not inputs:
            print(f"[{account_id}] 未找到{label}规格输入框")
            return

        current = inputs[-1]
        current.click()
        time.sleep(0.15)
        if not _react_fill_spec_input(page, current, name):
            current.input(name, clear=True)
            time.sleep(0.2)
            current.input("\n")
        time.sleep(0.35)
        page.run_js("arguments[0].blur();", current)
        _click_blank_area(page)
        print(f"[{account_id}] 已录入{label} ({i + 1}/{len(names)})：{name}")


def _ensure_second_spec_box(page, account_id: str):
    """尝试添加第二个规格维度（型号）。"""
    _, boxes = _spec_row_boxes(page)
    if len(boxes) >= 2:
        return boxes

    add_btn = page.ele("text:添加规格类型", timeout=2) or page.ele("text:添加规格", timeout=2)
    if add_btn:
        add_btn.click()
        time.sleep(1.5)
        _, boxes = _spec_row_boxes(page)
        print(f"[{account_id}] 已点击添加规格，当前 {len(boxes)} 个规格组")
    return boxes


def _select_spec_type(box, type_name: str, page, account_id: str) -> bool:
    """在规格组下拉框中选择「款式」或「尺寸」；选项限定在当前规格组/可见下拉内。"""
    if not box:
        return False
    trigger = box.ele("css:.ant-select-selector", timeout=1) or box.ele("tag:select", timeout=1)
    if not trigger:
        return False
    try:
        trigger.click()
    except Exception:
        page.run_js("arguments[0].click();", trigger)
    time.sleep(0.5)

    candidates = (
        f"css:.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option:has-text('{type_name}')",
        f"css:[class*='select-dropdown']:not([class*='hidden']) [class*='option']:has-text('{type_name}')",
    )
    for locator in candidates:
        option = page.ele(locator, timeout=1)
        if option:
            try:
                option.click()
            except Exception:
                page.run_js("arguments[0].click();", option)
            time.sleep(0.5)
            print(f"[{account_id}] 已选择规格类型：{type_name}", flush=True)
            return True

    try:
        picked = page.run_js(
            """
            const typeName = arguments[0];
            for (const panel of document.querySelectorAll(
                '.ant-select-dropdown:not(.ant-select-dropdown-hidden), [class*="select-dropdown"]:not([class*="hidden"])'
            )) {
                for (const el of panel.querySelectorAll('[class*="option"], li, div, span')) {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t !== typeName && !t.startsWith(typeName)) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 2 || r.height < 2) continue;
                    el.click();
                    return true;
                }
            }
            return false;
            """,
            type_name,
        )
        if picked:
            time.sleep(0.5)
            print(f"[{account_id}] 已选择规格类型（下拉）：{type_name}", flush=True)
            return True
    except Exception:
        pass
    return False


def _count_spec_price_rows(page) -> int:
    try:
        return int(page.run_js(_FIND_MARK_SKU_ROWS_JS) or 0)
    except Exception:
        return len(_sku_price_table_rows(page, scroll=False))


def _spec_lists_json(
    style_names: list[str] | None,
    size_names: list[str] | None,
) -> tuple[str, str]:
    return (
        json.dumps(list(style_names or []), ensure_ascii=False),
        json.dumps(list(size_names or []), ensure_ascii=False),
    )


def _activate_spec_price_table(
    page,
    style_names: list[str],
    size_names: list[str],
    *,
    account_id: str = "",
) -> None:
    """规格录入后滚动价格表容器，促使虚拟滚动矩阵渲染完整。"""
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    _scroll_to_price_table(page)
    _click_blank_area(page)
    try:
        page.run_js(_SCROLL_LOAD_ALL_ROWS_JS, str(len(style_names) * len(size_names)), styles_json, sizes_json)
    except Exception:
        pass
    time.sleep(0.4)
    if account_id:
        _sku_table_debug_snapshot(
            page, account_id, "after_activate_price_table", style_names, size_names
        )


def _wait_spec_matrix_rows(
    page,
    account_id: str,
    style_names: list[str],
    model_names: list[str],
    *,
    max_wait: int = 25,
) -> int:
    """规格录入后等待价格表行数 = 款式数 × 尺寸数。"""
    expected = len(style_names) * len(model_names)
    if expected <= 0:
        return 0
    styles_json, sizes_json = _spec_lists_json(style_names, model_names)
    for attempt in range(max_wait):
        _click_blank_area(page)
        try:
            count = int(
                page.run_js(_SCROLL_LOAD_ALL_ROWS_JS, str(expected), styles_json, sizes_json) or 0
            )
        except Exception:
            count = _count_spec_price_rows(page)
        if count >= expected:
            print(
                f"[{account_id}] 规格矩阵已生成 {count}/{expected} 行",
                flush=True,
            )
            _sku_table_debug_snapshot(
                page, account_id, "matrix_ready", style_names, model_names
            )
            return count
        if attempt == 0 or (attempt + 1) % 5 == 0:
            print(
                f"[{account_id}] 等待规格矩阵行数 ({count}/{expected}) "
                f"({attempt + 1}/{max_wait})",
                flush=True,
            )
        if attempt % 3 == 2:
            _activate_spec_price_table(
                page, style_names, model_names, account_id=account_id
            )
        time.sleep(0.6)
    try:
        count = int(
            page.run_js(_SCROLL_LOAD_ALL_ROWS_JS, str(expected), styles_json, sizes_json) or 0
        )
    except Exception:
        count = _count_spec_price_rows(page)
    print(
        f"[{account_id}] 规格矩阵行数未齐 ({count}/{expected})，继续尝试填表",
        flush=True,
    )
    _sku_table_debug_snapshot(
        page, account_id, "matrix_timeout", style_names, model_names
    )
    return count


def add_style_and_model_specs(
    page,
    account_id: str,
    style_names: list[str],
    model_names: list[str],
):
    """
    录入两个规格维度。
    第 1 组 → 款式（AI 颜色）；第 2 组 → 尺寸（商品类型分组）。
    """
    _, boxes = _spec_row_boxes(page)
    if not boxes:
        print(f"[{account_id}] 未找到 #spec 规格区域")
        return False

    _select_spec_type(boxes[0], "款式", page, account_id)
    _add_values_to_spec_box(page, boxes[0], account_id, "款式", style_names)
    _click_blank_area(page)
    time.sleep(0.5)

    boxes = _ensure_second_spec_box(page, account_id)
    _, boxes = _spec_row_boxes(page)
    second_label = "尺寸"
    if len(boxes) < 2:
        print(f"[{account_id}] 未能创建第二个规格组（尺寸），仍将尝试继续")
        if boxes:
            _add_values_to_spec_box(page, boxes[0], account_id, second_label, model_names)
        return False

    if not _select_spec_type(boxes[1], second_label, page, account_id):
        _select_spec_type(boxes[1], "型号", page, account_id)
    _add_values_to_spec_box(page, boxes[1], account_id, second_label, model_names)
    _click_blank_area(page)
    _wait_spec_matrix_rows(page, account_id, style_names, model_names)
    _activate_spec_price_table(
        page, style_names, model_names, account_id=account_id
    )
    print(f"[{account_id}] 款式、尺寸已全部录入，准备填写下方价格表...", flush=True)
    page.run_js("document.querySelector('.sku-table,.sku-list')?.scrollIntoView({block:'center'});")
    time.sleep(0.8)
    return True


_SKU_ROW_ATTR = "data-pdd-sku-row"
_PREVIEW_IDX_ATTR = "data-pdd-preview-idx"
_PREVIEW_CELL_ATTR = "data-pdd-preview-cell"

_JS_PREVIEW_ROW_HELPERS = """
function getSkuRowsForPreview() {
    let rows = [...document.querySelectorAll('tr[data-pdd-sku-row]')];
    if (rows.length) {
        rows.sort((a, b) => {
            const ai = parseInt(a.getAttribute('data-pdd-sku-row') || '999', 10);
            const bi = parseInt(b.getAttribute('data-pdd-sku-row') || '999', 10);
            return ai - bi;
        });
        return rows;
    }
    return [...document.querySelectorAll(
        '.sku-table tr[data-testid="beast-core-table-body-tr"], '
        + '.sku-list tr[data-testid="beast-core-table-body-tr"]'
    )].filter(tr => tr.querySelector('.sku-preview-cell'));
}

function getSkuRowByIndex(idx) {
    const rows = getSkuRowsForPreview();
    return rows[idx]
        || document.querySelector('tr[data-pdd-sku-row="' + idx + '"]')
        || null;
}

function getPreviewCell(idx) {
    const tr = getSkuRowByIndex(idx);
    const fromTr = tr?.querySelector('.sku-preview-cell, td[class*="sku-preview"]');
    if (fromTr) return fromTr;
    return document.querySelector('td[data-pdd-preview-cell="' + idx + '"]');
}

function previewCellNeedsUpload(cell) {
    if (!cell) return true;
    const text = (cell.innerText || cell.textContent || '').replace(/\\s+/g, '');
    if (text.includes('请上传预览图') || text.includes('上传预览图')) return true;
    return false;
}

function isProductPreviewThumb(img) {
    const rect = img.getBoundingClientRect();
    const w = rect.width || 0;
    const h = rect.height || 0;
    if (w < 20 || h < 20) return false;
    const src = (img.src || img.getAttribute('src') || '').toLowerCase();
    if (src.startsWith('blob:') || src.startsWith('data:image')) return true;
    if (src.includes('http')) return true;
    const nw = img.naturalWidth || 0;
    const nh = img.naturalHeight || 0;
    if (nw >= 30 || nh >= 30) return true;
    return w >= 36 && h >= 36;
}

function checkPreviewCellUploaded(cell) {
    if (!cell || previewCellNeedsUpload(cell)) return false;
    if (cell.querySelector(
        '[class*="delete"], [class*="close"], [class*="remove"], [class*="del"]'
    )) return true;
    for (const img of cell.querySelectorAll('img')) {
        if (isProductPreviewThumb(img)) return true;
    }
    for (const el of cell.querySelectorAll('div, span')) {
        const bg = getComputedStyle(el).backgroundImage || '';
        if (bg !== 'none' && bg.includes('url(')) {
            const r = el.getBoundingClientRect();
            if (r.width >= 28 && r.height >= 28) return true;
        }
    }
    return false;
}

function isPreviewUploaded(idx) {
    return checkPreviewCellUploaded(getPreviewCell(idx));
}
"""

_MARK_PREVIEW_INPUTS_JS = (
    _JS_PREVIEW_ROW_HELPERS
    + """
document.querySelectorAll('input[data-pdd-preview-idx]').forEach(
    inp => inp.removeAttribute('data-pdd-preview-idx')
);
document.querySelectorAll('td[data-pdd-preview-cell]').forEach(
    td => td.removeAttribute('data-pdd-preview-cell')
);
const rows = getSkuRowsForPreview();
let marked = 0;
rows.forEach((tr, idx) => {
    const cell = tr.querySelector('.sku-preview-cell, td[class*="sku-preview"]');
    let inp = cell?.querySelector('input[type="file"]');
    if (!inp && cell) {
        inp = [...cell.querySelectorAll('input')].find(i => {
            const t = (i.type || '').toLowerCase();
            return t === 'file' || (i.accept || '').includes('image');
        });
    }
    if (inp) {
        inp.setAttribute('data-pdd-preview-idx', String(idx));
        marked++;
    } else if (cell) {
        cell.setAttribute('data-pdd-preview-cell', String(idx));
        marked++;
    }
});
return marked;
"""
)

_CLICK_PREVIEW_CELL_JS = (
    _JS_PREVIEW_ROW_HELPERS
    + """
const idx = parseInt(arguments[0], 10);
const tr = getSkuRowByIndex(idx);
const cell = getPreviewCell(idx);
if (!cell) return false;
cell.scrollIntoView({block: 'nearest'});
if (isPreviewUploaded(idx)) return true;
const uploadBtn = cell.querySelector(
    '[class*="upload"], [class*="Upload"], .ant-upload, svg'
);
(uploadBtn || cell).click();
return true;
"""
)

_AFTER_CLICK_FIND_PREVIEW_INPUT_JS = (
    _JS_PREVIEW_ROW_HELPERS
    + """
const idx = parseInt(arguments[0], 10);
if (isPreviewUploaded(idx)) return true;
const tr = getSkuRowByIndex(idx);
const cell = getPreviewCell(idx);
if (!tr && !cell) return false;
let inp = cell?.querySelector('input[type="file"]');
if (!inp && tr) {
    for (const i of tr.querySelectorAll('input')) {
        const t = (i.type || '').toLowerCase();
        if (t === 'file' || (i.accept || '').includes('image')) {
            inp = i;
            break;
        }
    }
}
if (!inp) {
    for (const i of document.querySelectorAll('.sku-table input[type="file"]')) {
        if ((tr && tr.contains(i)) || (cell && cell.contains(i))) {
            inp = i;
            break;
        }
    }
}
if (inp) {
    inp.setAttribute('data-pdd-preview-idx', String(idx));
    return true;
}
return false;
"""
)

_IS_PREVIEW_UPLOADED_JS = (
    _JS_PREVIEW_ROW_HELPERS
    + """
return isPreviewUploaded(parseInt(arguments[0], 10));
"""
)

_MAX_PREVIEW_RETRIES = 3
_PREVIEW_VERIFY_TIMEOUT = 20.0
_PREVIEW_VERIFY_INTERVAL = 0.45
_PREVIEW_POST_INPUT_WAIT = 1.2

_PREVIEW_CHECK_ONLY_JS = """
const idx = parseInt(arguments[0], 10);
const tr = document.querySelector('tr[data-pdd-sku-row="' + idx + '"]');
const cell = tr?.querySelector('.sku-preview-cell');
if (!cell) return false;
const text = (cell.innerText || cell.textContent || '').replace(/\\s+/g, '');
if (text.includes('请上传预览图') || text.includes('上传预览图')) return false;
if (cell.querySelector('[class*="delete"], [class*="close"], [class*="remove"], [class*="del"]'))
    return true;
for (const img of cell.querySelectorAll('img')) {
    const r = img.getBoundingClientRect();
    const src = (img.src || img.getAttribute('src') || '').toLowerCase();
    if (r.width >= 20 && r.height >= 20) {
        if (src.includes('http') || src.startsWith('blob:') || src.startsWith('data:image'))
            return true;
        if (r.width >= 36 || r.height >= 36) return true;
    }
}
for (const el of cell.querySelectorAll('div, span')) {
    const bg = getComputedStyle(el).backgroundImage || '';
    if (bg !== 'none' && bg.includes('url(')) {
        const r = el.getBoundingClientRect();
        if (r.width >= 28 && r.height >= 28) return true;
    }
}
return false;
"""

_FIND_MARK_SKU_ROWS_JS = """
document.querySelectorAll('tr[data-pdd-sku-row]').forEach(tr => tr.removeAttribute('data-pdd-sku-row'));

function editableInputCount(tr) {
    let n = 0;
    for (const i of tr.querySelectorAll('input')) {
        const t = (i.type || '').toLowerCase();
        const ph = i.placeholder || '';
        if (!['file','hidden','checkbox','radio','button','submit'].includes(t)
            && !ph.includes('规格名称')) n++;
    }
    return n;
}

function isDataRow(tr) {
    return editableInputCount(tr) >= 3
        || tr.getAttribute('data-testid') === 'beast-core-table-body-tr';
}

function pickRows(node) {
    const out = [];
    if (!node) return out;
    for (const tr of node.querySelectorAll('tr[data-testid="beast-core-table-body-tr"]')) {
        if (isDataRow(tr)) out.push(tr);
    }
    if (out.length) return out;
    for (const tr of node.querySelectorAll('tbody tr')) {
        if (isDataRow(tr)) out.push(tr);
    }
    return out;
}

let best = [];

// 拼多多新版：.sku-table + beast-core-table
for (const root of document.querySelectorAll('.sku-table, .sku-list')) {
    const trs = pickRows(root);
    if (trs.length > best.length) best = trs;
}
if (best.length >= 2) {
    best.forEach((tr, i) => tr.setAttribute('data-pdd-sku-row', String(i)));
    return best.length;
}

// ant-table 旧版兜底
const spec = document.getElementById('spec');
let root = spec ? (spec.closest('form') || spec.parentElement) : null;
for (let d = 0; d < 8 && root; d++) {
    for (const tbody of root.querySelectorAll(
        '.ant-table-tbody, [data-testid="beast-core-table-middle-tbody"]'
    )) {
        const trs = pickRows(tbody);
        if (trs.length > best.length) best = trs;
    }
    if (best.length >= 2) break;
    root = root.parentElement;
}

best.forEach((tr, i) => tr.setAttribute('data-pdd-sku-row', String(i)));
return best.length;
"""


def _scroll_to_price_table(page):
    page.run_js(
        """
        const target = document.querySelector('.sku-table, .sku-list')
            || document.querySelector('[data-testid="beast-core-table-middle-tbody"]')
            || document.querySelector('.ant-table-tbody');
        if (target) target.scrollIntoView({block: 'center'});
        else window.scrollBy(0, 500);
        """
    )
    time.sleep(0.3)


def _is_editable_input(inp) -> bool:
    t = (inp.attr("type") or "text").lower()
    if t in ("file", "hidden", "checkbox", "radio", "button", "submit"):
        return False
    ph = inp.attr("placeholder") or ""
    if "规格名称" in ph:
        return False
    return True


def _row_data_inputs_from_cells(row):
    """按 td 顺序取库存/拼单价/单买价/规格编码（跳过款式、尺寸、预览图列）。"""
    inputs = []
    for td in row.eles("tag:td"):
        if td.eles("tag:input@type=file"):
            continue
        editable = [inp for inp in td.eles("tag:input") if _is_editable_input(inp)]
        if editable:
            inputs.append(editable[0])
    return inputs[:4]


def _row_data_inputs(row):
    """取一行内库存/拼单价/单买价/规格编码四个输入框。"""
    inputs = _row_data_inputs_from_cells(row)
    if len(inputs) >= 4:
        return inputs
    for sel in ("css:input.ant-input-number-input", "css:input.ant-input", "tag:input"):
        for inp in row.eles(sel):
            if _is_editable_input(inp) and inp not in inputs:
                inputs.append(inp)
    return inputs[:4] if len(inputs) >= 4 else inputs


def _sku_price_table_rows(page, scroll: bool = True):
    """定位 SKU 价格表行（兼容 beast-core-table / ant-table）。"""
    if scroll:
        _scroll_to_price_table(page)
    try:
        count = page.run_js(_FIND_MARK_SKU_ROWS_JS) or 0
    except Exception:
        count = 0
    if count:
        rows = page.eles(f"css:tr[{_SKU_ROW_ATTR}]", timeout=1)
        if rows:
            return rows

    for sel in (
        "css:.sku-table tr[data-testid=beast-core-table-body-tr]",
        "css:.sku-list tr[data-testid=beast-core-table-body-tr]",
        "css:.sku-table tbody tr",
        "css:.ant-table-tbody > tr",
    ):
        rows = page.eles(sel, timeout=1)
        rows = [
            r for r in rows
            if len(_row_data_inputs(r)) >= 3
            or r.attr("data-testid") == "beast-core-table-body-tr"
        ]
        if len(rows) >= 2:
            return rows
    return []


def _get_row_by_index(page, index: int):
    """每次重新取行元素，用 JS 滚动（避免 scroll.to_see 卡几分钟）。"""
    return _get_row_element(page, index)


def _cell_has_data_input(td) -> bool:
    for inp in td.eles("tag:input"):
        if _is_editable_input(inp):
            return True
    return False


def _sku_row_index_from_rows(rows) -> dict[tuple[str, str], object]:
    index: dict[tuple[str, str], object] = {}
    current_style = ""
    for row in rows:
        text_before_inputs = []
        for td in row.eles("tag:td"):
            if _cell_has_data_input(td):
                break
            text = (td.text or "").strip()
            if not text:
                continue
            text_before_inputs.append(text)
            if td.attr("rowspan"):
                current_style = text

        model = ""
        if len(text_before_inputs) >= 2:
            current_style = text_before_inputs[0]
            model = text_before_inputs[1]
        elif len(text_before_inputs) == 1:
            model = text_before_inputs[0]

        if current_style and model:
            index[(current_style, model)] = row
    return index


def _parse_scroll_find_result(raw) -> int | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict) and data.get("found") and int(data.get("idx", -1)) >= 0:
            return int(data["idx"])
    except Exception:
        return None
    return None


def _remark_sku_rows(page) -> int:
    try:
        return int(page.run_js(_FIND_MARK_SKU_ROWS_JS) or 0)
    except Exception:
        return 0


def _scroll_sku_table_to_load(
    page,
    expected: int,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> int:
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    try:
        return int(page.run_js(_SCROLL_LOAD_ALL_ROWS_JS, str(expected), styles_json, sizes_json) or 0)
    except Exception:
        return 0


def _ensure_style_size_row_visible(
    page,
    style_name: str,
    size_name: str,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> int | None:
    """滚动虚拟表格，按款式+尺寸定位行并返回 data-pdd-sku-row 索引。"""
    if not style_name or not size_name:
        return None
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    try:
        raw = page.run_js(_SCROLL_FIND_STYLE_SIZE_ROW_JS, style_name, size_name, styles_json, sizes_json)
        return _parse_scroll_find_result(raw)
    except Exception:
        return None


def _count_loaded_spec_rows(
    page,
    expected: int,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> int:
    """虚拟滚动表格：滚遍视口后统计「款式+尺寸」规格行数。"""
    return _scroll_sku_table_to_load(
        page,
        expected,
        style_names=style_names,
        size_names=size_names,
    )


def wait_multi_sku_rows(
    page,
    account_id: str,
    skus: list,
    max_wait: int = 15,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> list:
    """等待价格表生成，返回已定位的行元素列表。"""
    need = len(skus)
    matrix_need = (
        len(style_names) * len(size_names)
        if style_names and size_names
        else need
    )
    unique_pairs = _unique_sku_spec_pairs(skus)
    target = max(need, unique_pairs, matrix_need)
    max_wait = max(max_wait, min(60, target // 2 + 18))
    print(
        f"[{account_id}] 等待价格表生成（共需 {target} 行，"
        f"虚拟滚动下 DOM 可见行可能更少）...",
        flush=True,
    )
    rows: list = []
    spec_count = 0
    for attempt in range(max_wait):
        spec_count = _count_loaded_spec_rows(
            page,
            matrix_need or target,
            style_names=style_names,
            size_names=size_names,
        )
        rows = _sku_price_table_rows(page, scroll=(attempt == 0))
        ready = spec_count >= target or spec_count >= unique_pairs
        if ready:
            print(
                f"[{account_id}] 价格表就绪：规格行 {spec_count}（DOM 可见 {len(rows)} 行）",
                flush=True,
            )
            return rows
        if attempt == 0 or (attempt + 1) % 5 == 0:
            print(
                f"[{account_id}] 等待价格表 规格={spec_count}/{target} "
                f"可见={len(rows)} ({attempt + 1}/{max_wait})...",
                flush=True,
            )
        if attempt % 4 == 3:
            _click_blank_area(page)
            if style_names and size_names:
                _activate_spec_price_table(
                    page, style_names, size_names, account_id=account_id
                )
        time.sleep(0.6)
    spec_count = _count_loaded_spec_rows(
        page,
        matrix_need or target,
        style_names=style_names,
        size_names=size_names,
    )
    rows = _sku_price_table_rows(page, scroll=False)
    print(
        f"[{account_id}] 价格表未完全生成（规格 {spec_count}/{target}，"
        f"可见 {len(rows)} 行），继续尝试填写",
        flush=True,
    )
    return rows


def get_sku_row_by_style_model(page, style_name: str, model_name: str, max_wait: int = 12):
    target = (style_name, model_name)
    for _ in range(max_wait):
        rows = _sku_price_table_rows(page, scroll=False)
        row = _sku_row_index_from_rows(rows).get(target)
        if row:
            return row
        time.sleep(0.4)
    return None


def _mark_preview_inputs(page) -> int:
    """用 JS 标记 .sku-preview-cell 内的上传框（或单元格本身）。"""
    try:
        return page.run_js(_MARK_PREVIEW_INPUTS_JS) or 0
    except Exception:
        return 0


def _safe_preview_js(page, js: str, index: int, default=False):
    try:
        return page.run_js(js, str(index))
    except Exception:
        return default


def _resolve_preview_upload_input(
    page,
    index: int,
    style_name: str = "",
    size_name: str = "",
    *,
    spec_marker: str = "",
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
):
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    if style_name and size_name:
        _ensure_style_size_row_visible(
            page,
            style_name,
            size_name,
            style_names=style_names,
            size_names=size_names,
        )
        marker = str(spec_marker or index)
        try:
            raw = page.run_js(
                _RESOLVE_PREVIEW_INPUT_BY_SPEC_JS,
                style_name,
                size_name,
                marker,
                styles_json,
                sizes_json,
            ) or "{}"
            info = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(info, dict):
                if info.get("uploaded"):
                    return None
                if info.get("ready"):
                    marker_key = str(info.get("marker") or marker)
                    upload_input = page.ele(
                        f"css:input[data-pdd-preview-spec-idx='{marker_key}']",
                        timeout=0.5,
                    )
                    if upload_input:
                        return upload_input
                    cell = page.ele(
                        f"css:td[data-pdd-preview-spec-idx='{marker_key}']",
                        timeout=0.3,
                    )
                    if cell:
                        upload_input = cell.ele("xpath:.//input[@type='file']", timeout=0.5)
                        if upload_input:
                            return upload_input
        except Exception:
            pass

    if style_name and size_name:
        found_idx = _ensure_style_size_row_visible(
            page,
            style_name,
            size_name,
            style_names=style_names,
            size_names=size_names,
        )
        if found_idx is not None:
            index = found_idx

    if _preview_is_uploaded(
        page,
        index,
        style_name=style_name,
        size_name=size_name,
        style_names=style_names,
        size_names=size_names,
    ):
        return None

    upload_input = page.ele(f"css:input[{_PREVIEW_IDX_ATTR}='{index}']", timeout=0.2)
    if upload_input:
        return upload_input

    _safe_preview_js(page, _CLICK_PREVIEW_CELL_JS, index, default=False)
    time.sleep(0.45)
    if _preview_is_uploaded(
        page,
        index,
        style_name=style_name,
        size_name=size_name,
        style_names=style_names,
        size_names=size_names,
    ):
        return None
    _safe_preview_js(page, _AFTER_CLICK_FIND_PREVIEW_INPUT_JS, index, default=False)

    upload_input = page.ele(f"css:input[{_PREVIEW_IDX_ATTR}='{index}']", timeout=0.4)
    if upload_input:
        return upload_input

    cell = page.ele(f"css:td[{_PREVIEW_CELL_ATTR}='{index}']", timeout=0.3)
    if not cell:
        cell = page.ele(
            f"css:tr[{_SKU_ROW_ATTR}='{index}'] td.sku-preview-cell",
            timeout=0.3,
        )
    if cell:
        if _preview_is_uploaded(
            page,
            index,
            style_name=style_name,
            size_name=size_name,
            style_names=style_names,
            size_names=size_names,
        ):
            return None
        try:
            cell.click(by_js=True)
            time.sleep(0.35)
        except Exception:
            pass
        if _preview_is_uploaded(
            page,
            index,
            style_name=style_name,
            size_name=size_name,
            style_names=style_names,
            size_names=size_names,
        ):
            return None
        upload_input = cell.ele("xpath:.//input[@type='file']", timeout=0.5)
        if upload_input:
            return upload_input

    if _preview_is_uploaded(
        page,
        index,
        style_name=style_name,
        size_name=size_name,
        style_names=style_names,
        size_names=size_names,
    ):
        return None

    if style_name and size_name:
        return None

    inputs = page.eles("css:.sku-table input[type='file']", timeout=0.5)
    return inputs[index] if index < len(inputs) else None


def _preview_is_uploaded(
    page,
    index: int,
    *,
    style_name: str = "",
    size_name: str = "",
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> bool:
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    if style_name and size_name:
        try:
            if page.run_js(
                _PREVIEW_CHECK_BY_SPEC_JS,
                style_name,
                size_name,
                styles_json,
                sizes_json,
            ):
                return True
        except Exception:
            pass
        try:
            found_idx = _ensure_style_size_row_visible(
                page,
                style_name,
                size_name,
                style_names=style_names,
                size_names=size_names,
            )
            if found_idx is not None:
                index = found_idx
        except Exception:
            pass
    if _safe_preview_js(page, _PREVIEW_CHECK_ONLY_JS, index, default=False):
        return True
    if _safe_preview_js(page, _IS_PREVIEW_UPLOADED_JS, index, default=False):
        return True
    cell = page.ele(
        f"css:tr[{_SKU_ROW_ATTR}='{index}'] td.sku-preview-cell",
        timeout=0.15,
    )
    if not cell:
        return False
    text = (cell.text or "").replace(" ", "").replace("\n", "")
    if "请上传预览图" in text or "上传预览图" in text:
        return False
    return False


def _wait_preview_uploaded(
    page,
    index: int,
    timeout: float = _PREVIEW_VERIFY_TIMEOUT,
    interval: float = _PREVIEW_VERIFY_INTERVAL,
    *,
    style_name: str = "",
    size_name: str = "",
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> bool:
    deadline = _now() + timeout
    while _now() < deadline:
        if _preview_is_uploaded(
            page,
            index,
            style_name=style_name,
            size_name=size_name,
            style_names=style_names,
            size_names=size_names,
        ):
            return True
        time.sleep(interval)
    return _preview_is_uploaded(
        page,
        index,
        style_name=style_name,
        size_name=size_name,
        style_names=style_names,
        size_names=size_names,
    )


def upload_row_preview(
    page,
    index: int,
    image_path: str,
    account_id: str,
    label: str,
    *,
    style_name: str = "",
    size_name: str = "",
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
    max_retries: int = _MAX_PREVIEW_RETRIES,
) -> bool:
    total_t = _now()
    try:
        if style_name and size_name:
            found_idx = _ensure_style_size_row_visible(
                page,
                style_name,
                size_name,
                style_names=style_names,
                size_names=size_names,
            )
            if found_idx is not None:
                index = found_idx

        if _preview_is_uploaded(
            page,
            index,
            style_name=style_name,
            size_name=size_name,
            style_names=style_names,
            size_names=size_names,
        ):
            print(f"[{account_id}] 预览图已存在，跳过 [{label}]", flush=True)
            _log_step(account_id, f"  预览图合计 #{index + 1}", total_t)
            return True

        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                print(
                    f"[{account_id}] 预览图重试 ({attempt}/{max_retries})：{label}",
                    flush=True,
                )
                time.sleep(0.4)

            t = _now()
            upload_input = _resolve_preview_upload_input(
                page,
                index,
                style_name=style_name,
                size_name=size_name,
                spec_marker=str(index),
                style_names=style_names,
                size_names=size_names,
            )
            _log_step(
                account_id,
                f"  预览图找上传框 #{index + 1} (第{attempt}次)",
                t,
            )
            if not upload_input:
                if _preview_is_uploaded(
                    page,
                    index,
                    style_name=style_name,
                    size_name=size_name,
                    style_names=style_names,
                    size_names=size_names,
                ):
                    _log_step(
                        account_id,
                        f"  预览图校验通过 #{index + 1} (第{attempt}次，补检)",
                        t,
                    )
                    print(
                        f"[{account_id}] 已上传预览图 [{label}]（补检确认）",
                        flush=True,
                    )
                    _log_step(account_id, f"  预览图合计 #{index + 1}", total_t)
                    return True
                print(
                    f"[{account_id}] 未找到 [{label}] 预览图上传框 (第{attempt}次)",
                    flush=True,
                )
                continue

            t = _now()
            try:
                upload_input.input(image_path)
            except Exception as exc:
                print(
                    f"[{account_id}] 预览图文件选择失败 [{label}] "
                    f"(第{attempt}次)：{_safe_exc(exc)}",
                    flush=True,
                )
                continue
            _log_step(
                account_id,
                f"  预览图文件上传 #{index + 1} (第{attempt}次)",
                t,
            )
            time.sleep(_PREVIEW_POST_INPUT_WAIT)

            t = _now()
            if _wait_preview_uploaded(
                page,
                index,
                style_name=style_name,
                size_name=size_name,
                style_names=style_names,
                size_names=size_names,
            ):
                _log_step(
                    account_id,
                    f"  预览图校验通过 #{index + 1} (第{attempt}次)",
                    t,
                )
                print(f"[{account_id}] 已上传预览图 [{label}]", flush=True)
                _log_step(account_id, f"  预览图合计 #{index + 1}", total_t)
                return True

            _log_step(
                account_id,
                f"  预览图校验未通过 #{index + 1} (第{attempt}次)",
                t,
            )
            if _preview_is_uploaded(
                page,
                index,
                style_name=style_name,
                size_name=size_name,
                style_names=style_names,
                size_names=size_names,
            ):
                _log_step(
                    account_id,
                    f"  预览图校验通过 #{index + 1} (第{attempt}次，延迟补检)",
                    t,
                )
                print(
                    f"[{account_id}] 已上传预览图 [{label}]（延迟补检确认）",
                    flush=True,
                )
                _log_step(account_id, f"  预览图合计 #{index + 1}", total_t)
                return True
            print(
                f"[{account_id}] 预览图未检测到缩略图 [{label}] (第{attempt}次)",
                flush=True,
            )

        print(
            f"[{account_id}] 预览图上传失败（已重试 {max_retries} 次）[{label}]",
            flush=True,
        )
        return False
    except Exception as e:
        err = _safe_exc(e)
        if "连接已断开" in err or "disconnect" in err.lower():
            print(f"[{account_id}] 预览图上传中断 [{label}]：浏览器连接已断开", flush=True)
            raise
        print(f"[{account_id}] 预览图上传失败 [{label}]：{err}")
        return False


_JS_FILL_HELPERS = """
function rowInputs(tr) {
    const inputs = [];
    for (const td of tr.querySelectorAll('td')) {
        if (td.querySelector('input[type="file"]')) continue;
        for (const inp of td.querySelectorAll('input')) {
            const t = (inp.type || '').toLowerCase();
            if (!['file','hidden','checkbox','radio','button','submit'].includes(t)) {
                inputs.push(inp);
                break;
            }
        }
    }
    return inputs;
}

function isSkuDataRow(tr) {
    if (!tr.querySelector('.sku-preview-cell')) return false;
    let n = 0;
    for (const inp of tr.querySelectorAll('input')) {
        const t = (inp.type || '').toLowerCase();
        if (!['file','hidden','checkbox','radio','button','submit'].includes(t)) n++;
    }
    return n >= 3;
}

function getAllDataRows() {
    const beasts = [...document.querySelectorAll(
        '.sku-table tr[data-testid="beast-core-table-body-tr"], '
        + '.sku-list tr[data-testid="beast-core-table-body-tr"]'
    )].filter(isSkuDataRow);
    if (beasts.length) return beasts;
    const marked = [...document.querySelectorAll('tr[data-pdd-sku-row]')];
    if (marked.length) {
        marked.sort((a, b) => {
            const ai = parseInt(a.getAttribute('data-pdd-sku-row') || '999', 10);
            const bi = parseInt(b.getAttribute('data-pdd-sku-row') || '999', 10);
            return ai - bi;
        });
        return marked;
    }
    return [];
}

function getRow(idx) {
    const marked = document.querySelector('tr[data-pdd-sku-row="' + idx + '"]');
    if (marked) return marked;
    const rows = getAllDataRows();
    return rows[idx] || null;
}

function fillRow(idx, vals) {
    scrollRowIndexIntoView(idx);
    const tr = getRow(idx);
    if (!tr) return 0;
    return fillRowReliable(tr, vals);
}

function fillRowDirect(tr, vals) {
    return fillRowReliable(tr, vals);
}

function fillRowReliable(tr, vals) {
    if (!tr) return 0;
    try {
        tr.scrollIntoView({block: 'nearest', behavior: 'instant'});
    } catch (e) {
        tr.scrollIntoView({block: 'nearest'});
    }
    const inputs = rowInputs(tr);
    if (inputs.length < 4) return 0;
    const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
    ).set;
    for (let i = 0; i < 4; i++) {
        const el = inputs[i];
        const val = String(vals[i]);
        try { el.focus({preventScroll: true}); } catch (e) { try { el.focus(); } catch (e2) {} }
        setter.call(el, val);
        el.dispatchEvent(new InputEvent('input', {
            bubbles: true, data: val, inputType: 'insertText'
        }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        try { el.blur(); } catch (e) {}
    }
    return inputs.length;
}
"""

_FILL_ROWS_JS = (
    _JS_FILL_HELPERS
    + """
const allVals = JSON.parse(arguments[0]);
const rows = getAllDataRows();
let ok = 0;
for (let i = 0; i < allVals.length && i < rows.length; i++) {
    if (fillRowDirect(rows[i], allVals[i]) >= 4) ok++;
}
return ok;
"""
)

_FILL_ROWS_MAPPED_JS = (
    _JS_FILL_HELPERS
    + """
const items = JSON.parse(arguments[0]);
let ok = 0;
for (const item of items) {
    if (fillRow(item.idx, item.vals) >= 4) ok++;
}
return ok;
"""
)

_FILL_ROW_AT_INDEX_JS = (
    _JS_FILL_HELPERS
    + """
return fillRow(parseInt(arguments[0], 10), JSON.parse(arguments[1]));
"""
)

_STYLE_SIZE_MAP_JS = """
function cellHasDataInput(td) {
    for (const inp of td.querySelectorAll('input')) {
        const t = (inp.type || '').toLowerCase();
        if (!['file','hidden','checkbox','radio','button','submit'].includes(t)) return true;
    }
    return false;
}

function normSpecLabel(text) {
    let t = String(text || '');
    const pairs = [
        ['（', '('], ['）', ')'], ['＋', '+'],
        ['\u00a0', ''], [' ', ''],
    ];
    for (const [a, b] of pairs) t = t.split(a).join(b);
    return t.trim();
}

function normCellText(td) {
    const raw = (td.textContent || td.innerText || '').replace(/\\s+/g, ' ').trim();
    return normSpecLabel(raw) || raw;
}

function parseSpecLists(styleNamesJson, sizeNamesJson) {
    let styleNames = [];
    let sizeNames = [];
    try {
        if (styleNamesJson) styleNames = JSON.parse(styleNamesJson) || [];
        if (sizeNamesJson) sizeNames = JSON.parse(sizeNamesJson) || [];
    } catch (e) {}
    return {
        styleNames: styleNames.map(normSpecLabel).filter(Boolean),
        sizeNames: sizeNames.map(normSpecLabel).filter(Boolean),
    };
}

function globalSpecIndex(style, size, styleNames, sizeNames) {
    const ns = normSpecLabel(style);
    const nm = normSpecLabel(size);
    const si = styleNames.indexOf(ns);
    const zi = sizeNames.indexOf(nm);
    if (si < 0 || zi < 0) return -1;
    return si * sizeNames.length + zi;
}

function styleSizeKey(style, size) {
    return normSpecLabel(style) + '\\0' + normSpecLabel(size);
}

function parseRowStyleSize(tr, styleNames, sizeNames, currentStyle) {
    if (!tr || !styleNames.length || !sizeNames.length) return null;
    let foundStyle = '';
    let foundSize = '';
    let carryStyle = normSpecLabel(currentStyle || '');
    for (const td of tr.querySelectorAll('td')) {
        if (cellHasDataInput(td)) break;
        const text = normCellText(td);
        if (!text) continue;
        if (styleNames.includes(text)) {
            foundStyle = text;
            if (td.getAttribute('rowspan')) carryStyle = text;
        } else if (sizeNames.includes(text)) {
            foundSize = text;
        }
    }
    if (!foundStyle && carryStyle && styleNames.includes(carryStyle)) {
        foundStyle = carryStyle;
    }
    if (foundStyle && foundSize && foundStyle !== foundSize) {
        return { style: foundStyle, size: foundSize, nextStyle: foundStyle };
    }
    return carryStyle ? { style: '', size: '', nextStyle: carryStyle } : null;
}

function collectSkuDataRowElements() {
    const out = [];
    const sels = [
        '.sku-table tr[data-testid="beast-core-table-body-tr"]',
        '.sku-list tr[data-testid="beast-core-table-body-tr"]',
    ];
    for (const sel of sels) {
        for (const tr of document.querySelectorAll(sel)) {
            if (isSkuDataRow(tr)) out.push(tr);
        }
    }
    return out;
}

function scanVisibleSpecPairs(pairMap, ctx, doStamp) {
    const parsed = parseRowsWithRowspanContext(
        collectSkuDataRowElements(),
        ctx.styleNames,
        ctx.sizeNames
    );
    let added = 0;
    for (const item of parsed) {
        const key = styleSizeKey(item.style, item.size);
        if (pairMap[key]) continue;
        pairMap[key] = item.tr;
        added++;
        if (doStamp) {
            stampRowSpec(item.tr, item.style, item.size, ctx.styleNames, ctx.sizeNames);
        }
    }
    return added;
}

function orderedTrsFromPairMap(pairMap, ctx) {
    const ordered = [];
    for (const s of ctx.styleNames) {
        for (const z of ctx.sizeNames) {
            const tr = pairMap[styleSizeKey(s, z)];
            if (tr) ordered.push(tr);
        }
    }
    return ordered;
}

function collectAllSkuRowsByScrolling(styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    const expected = ctx.styleNames.length * ctx.sizeNames.length;
    const pairMap = {};

    scrollSkuTableToTop();
    scanVisibleSpecPairs(pairMap, ctx, false);

    const targets = getSkuScrollTargets();
    const stepPx = targets.length
        ? Math.max(36, Math.floor((targets[0].clientHeight || 200) * 0.2))
        : 72;

    for (let step = 0; step < 160; step++) {
        if (expected > 0 && Object.keys(pairMap).length >= expected) break;
        const moved = scrollSkuTableStep(stepPx);
        const added = scanVisibleSpecPairs(pairMap, ctx, false);
        if (!moved && added === 0) break;
    }

    for (const t of getSkuScrollTargets()) {
        t.scrollTop = t.scrollHeight;
        fireSkuTableScroll(t);
    }
    scanVisibleSpecPairs(pairMap, ctx, false);
    scrollSkuTableToTop();
    return orderedTrsFromPairMap(pairMap, ctx);
}

function parseRowsWithRowspanContext(rows, styleNames, sizeNames) {
    const out = [];
    let currentStyle = '';
    for (const tr of rows) {
        let rowStyle = '';
        let rowSize = '';
        for (const td of tr.querySelectorAll('td')) {
            if (cellHasDataInput(td)) break;
            const text = normCellText(td);
            if (!text) continue;
            if (styleNames.includes(text)) {
                rowStyle = text;
                if (td.getAttribute('rowspan')) currentStyle = text;
            } else if (sizeNames.includes(text)) {
                rowSize = text;
            }
        }
        const style = rowStyle || currentStyle;
        if (style && rowSize && style !== rowSize) {
            out.push({ tr, style, size: rowSize });
        }
    }
    return out;
}

function stampRowSpec(tr, style, size, styleNames, sizeNames) {
    if (!tr) return -1;
    const gi = globalSpecIndex(style, size, styleNames, sizeNames);
    tr.setAttribute('data-pdd-spec-style', style);
    tr.setAttribute('data-pdd-spec-size', size);
    if (gi >= 0) tr.setAttribute('data-pdd-sku-row', String(gi));
    return gi;
}

function findVisibleSpecRow(style, size, styleNames, sizeNames) {
    const ns = normSpecLabel(style);
    const nm = normSpecLabel(size);
    const parsed = parseRowsWithRowspanContext(
        collectSkuDataRowElements(),
        styleNames,
        sizeNames
    );
    for (const item of parsed) {
        if (normSpecLabel(item.style) === ns && normSpecLabel(item.size) === nm) {
            try {
                item.tr.scrollIntoView({block: 'center', behavior: 'instant'});
            } catch (e) {
                item.tr.scrollIntoView({block: 'center'});
            }
            const gi = stampRowSpec(item.tr, item.style, item.size, styleNames, sizeNames);
            return { tr: item.tr, idx: gi };
        }
    }
    return null;
}

function buildStyleSizeRowMap(styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    const styleNames = ctx.styleNames;
    const sizeNames = ctx.sizeNames;
    const map = {};
    for (const tr of document.querySelectorAll('tr[data-pdd-spec-style][data-pdd-spec-size]')) {
        const style = tr.getAttribute('data-pdd-spec-style') || '';
        const size = tr.getAttribute('data-pdd-spec-size') || '';
        if (!style || !size) continue;
        const marked = tr.getAttribute('data-pdd-sku-row');
        const rowIdx = marked !== null && marked !== '' ? parseInt(marked, 10) : -1;
        map[styleSizeKey(style, size)] = { tr: tr, idx: Number.isFinite(rowIdx) ? rowIdx : -1 };
    }
    if (!styleNames.length || !sizeNames.length) return map;
    const rows = collectAllSkuRowsByScrolling(styleNamesJson, sizeNamesJson);
    for (const item of parseRowsWithRowspanContext(rows, styleNames, sizeNames)) {
        const key = styleSizeKey(item.style, item.size);
        if (map[key]) continue;
        const gi = globalSpecIndex(item.style, item.size, styleNames, sizeNames);
        map[key] = { tr: item.tr, idx: gi >= 0 ? gi : -1 };
    }
    return map;
}

function findStyleSizeHit(style, size, styleNamesJson, sizeNamesJson) {
    const map = buildStyleSizeRowMap(styleNamesJson, sizeNamesJson);
    const key = styleSizeKey(style, size);
    if (map[key]) return map[key];
    const ns = normSpecLabel(style);
    const nm = normSpecLabel(size);
    for (const k of Object.keys(map)) {
        const parts = k.split('\\0');
        if (parts[0] === ns && parts[1] === nm) return map[k];
    }
    return null;
}

function dumpStyleSizeMap(styleNamesJson, sizeNamesJson) {
    const map = buildStyleSizeRowMap(styleNamesJson, sizeNamesJson);
    const out = [];
    for (const k of Object.keys(map)) {
        const parts = k.split('\\0');
        out.push({
            style: parts[0] || '',
            size: parts[1] || '',
            idx: map[k].idx,
        });
    }
    out.sort((a, b) => (a.idx || 0) - (b.idx || 0));
    return JSON.stringify(out);
}
"""

_SKU_TABLE_SCROLL_JS = (
    _JS_FILL_HELPERS
    + _STYLE_SIZE_MAP_JS
    + """
function getSkuScrollTargets() {
    const targets = [];
    const seen = new Set();

    function isScrollable(el) {
        if (!el) return false;
        const st = getComputedStyle(el);
        const oy = st.overflowY || st.overflow;
        return (oy === 'auto' || oy === 'scroll' || oy === 'overlay')
            && el.scrollHeight > el.clientHeight + 4;
    }

    function add(el) {
        if (!el || seen.has(el) || !isScrollable(el)) return;
        seen.add(el);
        targets.push(el);
    }

    const sampleRow = document.querySelector(
        '.sku-table tr[data-testid="beast-core-table-body-tr"], '
        + '.sku-list tr[data-testid="beast-core-table-body-tr"]'
    );
    if (sampleRow) {
        let el = sampleRow.parentElement;
        while (el && el !== document.documentElement) {
            add(el);
            el = el.parentElement;
        }
    }

    const extraSels = [
        '[data-testid="beast-core-table-middle-body"]',
        '[data-testid="beast-core-table-body"]',
        '[data-testid="beast-core-table-middle-tbody"]',
        '.beast-core-table-body',
        '.sku-table',
        '.sku-list',
    ];
    for (const sel of extraSels) {
        for (const el of document.querySelectorAll(sel)) add(el);
    }

    const roots = [...document.querySelectorAll('.sku-table, .sku-list')];
    for (const root of roots) {
        for (const el of root.querySelectorAll('*')) add(el);
    }

    targets.sort((a, b) => {
        const aHas = a.querySelector('tr[data-testid="beast-core-table-body-tr"]') ? 0 : 1;
        const bHas = b.querySelector('tr[data-testid="beast-core-table-body-tr"]') ? 0 : 1;
        if (aHas !== bHas) return aHas - bHas;
        return (a.scrollHeight - a.clientHeight) - (b.scrollHeight - b.clientHeight);
    });
    return targets;
}

function fireSkuTableScroll(el) {
    if (!el) return;
    try {
        el.dispatchEvent(new Event('scroll', { bubbles: true }));
    } catch (e) {}
}

function scrollSkuTableStep(delta) {
    const targets = getSkuScrollTargets();
    let moved = false;
    for (const t of targets) {
        const before = t.scrollTop;
        const maxTop = Math.max(0, t.scrollHeight - t.clientHeight);
        t.scrollTop = Math.max(0, Math.min(before + delta, maxTop));
        if (t.scrollTop !== before) {
            moved = true;
            fireSkuTableScroll(t);
        }
    }
    return moved;
}

function scrollSkuTableToTop() {
    const targets = getSkuScrollTargets();
    for (const t of targets) {
        t.scrollTop = 0;
        fireSkuTableScroll(t);
    }
    return targets;
}

function scrollFindStyleSizeRow(style, size, styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    const gi = globalSpecIndex(style, size, ctx.styleNames, ctx.sizeNames);
    if (gi < 0) return {found: false, idx: -1};

    let tr = getRowBySpec(style, size, styleNamesJson, sizeNamesJson);
    if (tr) {
        try {
            tr.scrollIntoView({block: 'center', behavior: 'instant'});
        } catch (e) {
            tr.scrollIntoView({block: 'center'});
        }
        return {found: true, idx: gi};
    }

    const expected = ctx.styleNames.length * ctx.sizeNames.length;
    const targets = getSkuScrollTargets();
    const stepPx = targets.length
        ? Math.max(36, Math.floor((targets[0].clientHeight || 200) * 0.2))
        : 72;

    function tryFind() {
        const hit = findVisibleSpecRow(style, size, ctx.styleNames, ctx.sizeNames);
        if (hit) return {found: true, idx: hit.idx >= 0 ? hit.idx : gi};
        return null;
    }

    let hit = tryFind();
    if (hit) return hit;

    scrollSkuTableToTop();
    hit = tryFind();
    if (hit) return hit;

    if (targets.length && expected > 1) {
        const ratio = gi / (expected - 1);
        for (const t of targets) {
            t.scrollTop = ratio * Math.max(0, t.scrollHeight - t.clientHeight);
            fireSkuTableScroll(t);
        }
        hit = tryFind();
        if (hit) return hit;
    }

    for (let step = 0; step < 160; step++) {
        hit = tryFind();
        if (hit) return hit;
        const moved = scrollSkuTableStep(stepPx);
        hit = tryFind();
        if (hit) return hit;
        if (!moved) break;
    }

    for (const t of targets) {
        t.scrollTop = t.scrollHeight;
        fireSkuTableScroll(t);
    }
    hit = tryFind();
    return hit || {found: false, idx: -1};
}

function countStyleSizeRows(styleNamesJson, sizeNamesJson) {
    return Object.keys(buildStyleSizeRowMap(styleNamesJson, sizeNamesJson)).length;
}

function countKnownSpecRows(styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    const expected = ctx.styleNames.length * ctx.sizeNames.length;
    if (!expected) return countStyleSizeRows(styleNamesJson, sizeNamesJson);
    const pairMap = {};
    scrollSkuTableToTop();
    scanVisibleSpecPairs(pairMap, ctx, false);
    const targets = getSkuScrollTargets();
    const stepPx = targets.length
        ? Math.max(36, Math.floor((targets[0].clientHeight || 200) * 0.2))
        : 72;
    for (let step = 0; step < 160; step++) {
        if (Object.keys(pairMap).length >= expected) break;
        const moved = scrollSkuTableStep(stepPx);
        const added = scanVisibleSpecPairs(pairMap, ctx, false);
        if (!moved && added === 0) break;
    }
    for (const t of getSkuScrollTargets()) {
        t.scrollTop = t.scrollHeight;
        fireSkuTableScroll(t);
    }
    scanVisibleSpecPairs(pairMap, ctx, false);
    scrollSkuTableToTop();
    return Math.min(Object.keys(pairMap).length, expected);
}

function getRowBySpec(style, size, styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    const ns = normSpecLabel(style);
    const nm = normSpecLabel(size);
    const visible = parseRowsWithRowspanContext(
        collectSkuDataRowElements(),
        ctx.styleNames,
        ctx.sizeNames
    );
    for (const item of visible) {
        if (normSpecLabel(item.style) === ns && normSpecLabel(item.size) === nm) {
            stampRowSpec(item.tr, item.style, item.size, ctx.styleNames, ctx.sizeNames);
            return item.tr;
        }
    }
    for (const tr of document.querySelectorAll('tr[data-pdd-spec-style][data-pdd-spec-size]')) {
        if (normSpecLabel(tr.getAttribute('data-pdd-spec-style') || '') === ns
            && normSpecLabel(tr.getAttribute('data-pdd-spec-size') || '') === nm) {
            return tr;
        }
    }
    return null;
}

function stampGlobalRowIndices(styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    const expected = ctx.styleNames.length * ctx.sizeNames.length;
    if (!expected) return 0;
    const pairMap = {};

    scrollSkuTableToTop();
    scanVisibleSpecPairs(pairMap, ctx, true);

    const targets = getSkuScrollTargets();
    const stepPx = targets.length
        ? Math.max(36, Math.floor((targets[0].clientHeight || 200) * 0.2))
        : 72;

    for (let step = 0; step < 160; step++) {
        if (Object.keys(pairMap).length >= expected) break;
        const moved = scrollSkuTableStep(stepPx);
        scanVisibleSpecPairs(pairMap, ctx, true);
        if (!moved && Object.keys(pairMap).length >= expected) break;
        if (!moved) break;
    }

    for (const t of getSkuScrollTargets()) {
        t.scrollTop = t.scrollHeight;
        fireSkuTableScroll(t);
    }
    scanVisibleSpecPairs(pairMap, ctx, true);
    scrollSkuTableToTop();
    return Math.min(Object.keys(pairMap).length, expected);
}

function stampAllRowsByScroll(styleNamesJson, sizeNamesJson) {
    return stampGlobalRowIndices(styleNamesJson, sizeNamesJson);
}

function scrollRowIndexIntoView(idx, styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    if (ctx.styleNames.length && ctx.sizeNames.length && idx >= 0) {
        const zi = idx % ctx.sizeNames.length;
        const si = Math.floor(idx / ctx.sizeNames.length);
        const style = ctx.styleNames[si];
        const size = ctx.sizeNames[zi];
        if (style && size) {
            const found = scrollFindStyleSizeRow(style, size, styleNamesJson, sizeNamesJson);
            return !!(found && found.found);
        }
    }
    let tr = getRow(idx);
    if (tr) {
        try {
            tr.scrollIntoView({block: 'center', behavior: 'instant'});
        } catch (e) {
            tr.scrollIntoView({block: 'center'});
        }
        return true;
    }
    const targets = getSkuScrollTargets();
    for (const t of targets) {
        if (t.scrollHeight > t.clientHeight + 8) {
            const ratio = idx / Math.max(1, (ctx.styleNames.length * ctx.sizeNames.length) - 1);
            t.scrollTop = ratio * (t.scrollHeight - t.clientHeight);
            fireSkuTableScroll(t);
        }
    }
    tr = getRow(idx);
    if (tr) {
        try {
            tr.scrollIntoView({block: 'center', behavior: 'instant'});
        } catch (e) {
            tr.scrollIntoView({block: 'center'});
        }
        return true;
    }
    return false;
}

function rowHasRequiredValues(tr) {
    const inputs = rowInputs(tr);
    if (inputs.length < 4) return false;
    for (let i = 0; i < 4; i++) {
        if (!String(inputs[i].value || '').trim()) return false;
    }
    return true;
}

function verifyRowFilled(idx, styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    if (ctx.styleNames.length && ctx.sizeNames.length && idx >= 0) {
        const zi = idx % ctx.sizeNames.length;
        const si = Math.floor(idx / ctx.sizeNames.length);
        const style = ctx.styleNames[si];
        const size = ctx.sizeNames[zi];
        if (style && size) {
            scrollFindStyleSizeRow(style, size, styleNamesJson, sizeNamesJson);
            const tr = getRowBySpec(style, size, styleNamesJson, sizeNamesJson);
            return tr ? rowHasRequiredValues(tr) : false;
        }
    }
    scrollRowIndexIntoView(idx, styleNamesJson, sizeNamesJson);
    const tr = getRow(idx);
    return tr ? rowHasRequiredValues(tr) : false;
}

function verifyRowFilledBySpec(style, size, styleNamesJson, sizeNamesJson) {
    scrollFindStyleSizeRow(style, size, styleNamesJson, sizeNamesJson);
    const tr = getRowBySpec(style, size, styleNamesJson, sizeNamesJson);
    return tr ? rowHasRequiredValues(tr) : false;
}

function prepareSkuTableForFill(styleNamesJson, sizeNamesJson) {
    return stampGlobalRowIndices(styleNamesJson, sizeNamesJson);
}

function _clickBlankInTable() {
    for (const el of document.querySelectorAll('span,div,label,p')) {
        const t = (el.textContent || '').trim();
        if (t === '价格及库存' || t === '价格与库存') {
            el.click();
            return;
        }
    }
}
"""
)

_SCROLL_FIND_STYLE_SIZE_ROW_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
const style = arguments[0] || '';
const size = arguments[1] || '';
const styleNamesJson = arguments[2] || '[]';
const sizeNamesJson = arguments[3] || '[]';
const result = scrollFindStyleSizeRow(style, size, styleNamesJson, sizeNamesJson);
return JSON.stringify(result);
"""
)

_SCROLL_LOAD_ALL_ROWS_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
const expected = parseInt(arguments[0], 10) || 0;
const styleNamesJson = arguments[1] || '[]';
const sizeNamesJson = arguments[2] || '[]';
const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
if (ctx.styleNames.length && ctx.sizeNames.length) {
    return countKnownSpecRows(styleNamesJson, sizeNamesJson);
}
const targets = getSkuScrollTargets();
const pairMap = {};
scanVisibleSpecPairs(pairMap, ctx, false);
let best = Object.keys(pairMap).length;
if (!targets.length) {
    window.scrollTo(0, document.body.scrollHeight);
    scanVisibleSpecPairs(pairMap, ctx, false);
    best = Math.max(best, Object.keys(pairMap).length);
    return best;
}
scrollSkuTableToTop();
scanVisibleSpecPairs(pairMap, ctx, false);
best = Math.max(best, Object.keys(pairMap).length);
const stepPx = targets.length
    ? Math.max(60, Math.floor((targets[0].clientHeight || 200) * 0.35))
    : 80;
for (let step = 0; step < 96; step++) {
    if (expected > 0 && best >= expected) break;
    const moved = scrollSkuTableStep(stepPx);
    scanVisibleSpecPairs(pairMap, ctx, false);
    best = Object.keys(pairMap).length;
    if (!moved) break;
}
for (const t of getSkuScrollTargets()) {
    t.scrollTop = t.scrollHeight;
    fireSkuTableScroll(t);
}
scanVisibleSpecPairs(pairMap, ctx, false);
best = Math.max(best, Object.keys(pairMap).length);
return best;
"""
)

_FILL_ONE_BY_STYLE_SIZE_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
const style = arguments[0] || '';
const size = arguments[1] || '';
const vals = JSON.parse(arguments[2]);
const styleNamesJson = arguments[3] || '[]';
const sizeNamesJson = arguments[4] || '[]';
const tr = getRowBySpec(style, size, styleNamesJson, sizeNamesJson);
if (!tr) return 0;
return fillRowReliable(tr, vals);
"""
)

_FILL_SKUS_BY_STYLE_SIZE_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
const items = JSON.parse(arguments[0]);
const styleNamesJson = arguments[1] || '[]';
const sizeNamesJson = arguments[2] || '[]';
let ok = 0;
const failed = [];
for (const item of items) {
    scrollFindStyleSizeRow(item.style, item.size, styleNamesJson, sizeNamesJson);
    const tr = getRowBySpec(item.style, item.size, styleNamesJson, sizeNamesJson);
    if (!tr) {
        failed.push({style: item.style || '', size: item.size || '', reason: 'row_not_found'});
        continue;
    }
    if (fillRowReliable(tr, item.vals) >= 4) ok++;
    else failed.push({style: item.style || '', size: item.size || '', reason: 'fill_failed'});
}
return JSON.stringify({ok: ok, failed: failed});
"""
)

_BUILD_STYLE_SIZE_ROW_MAP_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
const pairs = JSON.parse(arguments[0]);
const styleNamesJson = arguments[1] || '[]';
const sizeNamesJson = arguments[2] || '[]';
const out = [];
for (let i = 0; i < pairs.length; i++) {
    const p = pairs[i];
    scrollFindStyleSizeRow(p.style, p.size, styleNamesJson, sizeNamesJson);
    const hit = findStyleSizeHit(p.style, p.size, styleNamesJson, sizeNamesJson);
    out.push(hit ? hit.idx : i);
}
return JSON.stringify(out);
"""
)

_DIAGNOSE_FILL_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
const styleNamesJson = arguments[0] || '[]';
const sizeNamesJson = arguments[1] || '[]';
let inputsInFirst = 0;
const rows = getAllDataRows();
if (rows[0]) {
    inputsInFirst = rowInputs(rows[0]).length;
}
const trs = document.querySelectorAll(
    '.sku-table tr[data-testid="beast-core-table-body-tr"]'
);
const marked = document.querySelectorAll('tr[data-pdd-sku-row]');
const specMarked = document.querySelectorAll('tr[data-pdd-spec-style]');
return JSON.stringify({
    tableRows: trs.length,
    markedRows: marked.length,
    specMarkedRows: specMarked.length,
    dataRows: rows.length,
    inputsInFirst: inputsInFirst,
    pageSpecs: JSON.parse(dumpStyleSizeMap(styleNamesJson, sizeNamesJson))
});
"""
)


_STAMP_GLOBAL_ROW_INDICES_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
return prepareSkuTableForFill(arguments[0], arguments[1]);
"""
)

_STAMP_ROWS_BY_SCROLL_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
return stampGlobalRowIndices(arguments[0], arguments[1]);
"""
)

_VERIFY_ROW_FILLED_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
return verifyRowFilled(parseInt(arguments[0], 10), arguments[1] || '[]', arguments[2] || '[]');
"""
)

_VERIFY_ROW_FILLED_BY_SPEC_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
return verifyRowFilledBySpec(
    arguments[0] || '',
    arguments[1] || '',
    arguments[2] || '[]',
    arguments[3] || '[]'
);
"""
)

_RESOLVE_PREVIEW_INPUT_BY_SPEC_JS = (
    _SKU_TABLE_SCROLL_JS
    + _JS_PREVIEW_ROW_HELPERS
    + """
const style = arguments[0] || '';
const size = arguments[1] || '';
const marker = String(arguments[2] || '');
const styleNamesJson = arguments[3] || '[]';
const sizeNamesJson = arguments[4] || '[]';
scrollFindStyleSizeRow(style, size, styleNamesJson, sizeNamesJson);
const tr = getRowBySpec(style, size, styleNamesJson, sizeNamesJson);
if (!tr) return JSON.stringify({ready: false, uploaded: false});
try {
    tr.scrollIntoView({block: 'center', behavior: 'instant'});
} catch (e) {
    tr.scrollIntoView({block: 'center'});
}
const cell = tr.querySelector('.sku-preview-cell, td[class*="sku-preview"]');
if (!cell) return JSON.stringify({ready: false, uploaded: false});
if (checkPreviewCellUploaded(cell)) {
    return JSON.stringify({ready: true, uploaded: true});
}
let inp = cell.querySelector('input[type="file"]');
if (!inp) {
    const uploadBtn = cell.querySelector(
        '[class*="upload"], [class*="Upload"], .ant-upload, svg'
    );
    (uploadBtn || cell).click();
    inp = cell.querySelector('input[type="file"]');
}
if (inp) {
    inp.setAttribute('data-pdd-preview-spec-idx', marker);
    return JSON.stringify({ready: true, uploaded: false, marker: marker});
}
cell.setAttribute('data-pdd-preview-spec-idx', marker);
return JSON.stringify({ready: true, uploaded: false, marker: marker});
"""
)

_PREVIEW_CHECK_BY_SPEC_JS = (
    _SKU_TABLE_SCROLL_JS
    + _JS_PREVIEW_ROW_HELPERS
    + """
const style = arguments[0] || '';
const size = arguments[1] || '';
const styleNamesJson = arguments[2] || '[]';
const sizeNamesJson = arguments[3] || '[]';
scrollFindStyleSizeRow(style, size, styleNamesJson, sizeNamesJson);
const tr = getRowBySpec(style, size, styleNamesJson, sizeNamesJson);
if (!tr) return false;
const cell = tr.querySelector('.sku-preview-cell, td[class*="sku-preview"]');
return checkPreviewCellUploaded(cell);
"""
)

_DUMP_STYLE_SIZE_MAP_JS = (
    _SKU_TABLE_SCROLL_JS
    + "return dumpStyleSizeMap(arguments[0] || '[]', arguments[1] || '[]');"
)

# 临时诊断：配合 _sku_table_debug.py，稳定后整段删除
_SKU_TABLE_DEBUG_SNAPSHOT_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
function rowTextSample(tr) {
    const parts = [];
    for (const td of tr.querySelectorAll('td')) {
        if (cellHasDataInput(td)) break;
        const t = normCellText(td);
        if (t) parts.push(t);
    }
    return parts.join(' | ');
}

function skuTableDebugSnapshot(styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    const expected = ctx.styleNames.length * ctx.sizeNames.length;
    const targets = getSkuScrollTargets();
    const visibleRows = collectSkuDataRowElements();
    const collectedRows = collectAllSkuRowsByScrolling(styleNamesJson, sizeNamesJson);
    const parsed = parseRowsWithRowspanContext(
        collectedRows, ctx.styleNames, ctx.sizeNames
    );
    const map = buildStyleSizeRowMap(styleNamesJson, sizeNamesJson);
    const missing = [];
    for (const s of ctx.styleNames) {
        for (const z of ctx.sizeNames) {
            const k = styleSizeKey(s, z);
            if (!map[k]) missing.push({style: s, size: z});
        }
    }
    const scrollTargets = targets.slice(0, 8).map((t) => ({
        tag: t.tagName,
        className: String(t.className || '').slice(0, 100),
        scrollTop: Math.round(t.scrollTop || 0),
        scrollHeight: Math.round(t.scrollHeight || 0),
        clientHeight: Math.round(t.clientHeight || 0),
    }));
    const collectedSamples = [];
    const head = collectedRows.slice(0, 5);
    const tail = collectedRows.length > 8 ? collectedRows.slice(-3) : [];
    for (let i = 0; i < head.length; i++) {
        collectedSamples.push({i: i, text: rowTextSample(head[i])});
    }
    for (let j = 0; j < tail.length; j++) {
        collectedSamples.push({
            i: collectedRows.length - tail.length + j,
            text: rowTextSample(tail[j]),
        });
    }
    const unparsedSamples = [];
    for (let ri = 0; ri < collectedRows.length && unparsedSamples.length < 15; ri++) {
        const tr = collectedRows[ri];
        const cells = [];
        for (const td of tr.querySelectorAll('td')) {
            if (cellHasDataInput(td)) break;
            const t = normCellText(td);
            if (t) cells.push(t);
        }
        const hit = parsed.some((p) => p.tr === tr);
        if (!hit) {
            unparsedSamples.push({i: ri, cells: cells, text: rowTextSample(tr)});
        }
    }
    const visibleSamples = visibleRows.slice(0, 8).map((tr, i) => ({
        i: i,
        text: rowTextSample(tr),
    }));
    const domLabels = [];
    const labelSet = new Set();
    for (const tr of collectedRows) {
        for (const td of tr.querySelectorAll('td')) {
            if (cellHasDataInput(td)) break;
            const t = normCellText(td);
            if (!t || labelSet.has(t)) continue;
            labelSet.add(t);
            domLabels.push({
                text: t,
                isStyle: ctx.styleNames.includes(t),
                isSize: ctx.sizeNames.includes(t),
            });
        }
    }
    return JSON.stringify({
        expected: expected,
        styleNames: ctx.styleNames,
        sizeNames: ctx.sizeNames,
        scrollTargetCount: targets.length,
        scrollTargets: scrollTargets,
        visibleDataRowCount: visibleRows.length,
        collectedRowCount: collectedRows.length,
        parsedSpecPairCount: parsed.length,
        mappedSpecPairCount: Object.keys(map).length,
        stampedAttrCount: document.querySelectorAll('tr[data-pdd-spec-style]').length,
        domMarkedRowCount: document.querySelectorAll('tr[data-pdd-sku-row]').length,
        missingPairCount: missing.length,
        missingPairs: missing.slice(0, 40),
        parsedPairs: parsed.slice(0, 40).map((p, i) => ({
            i: i,
            style: p.style,
            size: p.size,
            idx: globalSpecIndex(p.style, p.size, ctx.styleNames, ctx.sizeNames),
        })),
        mapEntries: Object.keys(map).slice(0, 40).map((k) => {
            const parts = k.split('\\0');
            return {
                style: parts[0] || '',
                size: parts[1] || '',
                idx: map[k].idx,
            };
        }),
        collectedRowTextSamples: collectedSamples,
        visibleRowTextSamples: visibleSamples,
        unparsedRowSamples: unparsedSamples,
        domSpecLabels: domLabels.slice(0, 60),
    });
}
return skuTableDebugSnapshot(arguments[0] || '[]', arguments[1] || '[]');
"""
)

_SKU_TABLE_DEBUG_PROBE_JS = (
    _SKU_TABLE_SCROLL_JS
    + """
function probeStyleSizeRow(style, size, styleNamesJson, sizeNamesJson) {
    const ctx = parseSpecLists(styleNamesJson, sizeNamesJson);
    const map = buildStyleSizeRowMap(styleNamesJson, sizeNamesJson);
    const key = styleSizeKey(style, size);
    const mapEntry = map[key] || null;
    const scrollResult = scrollFindStyleSizeRow(style, size, styleNamesJson, sizeNamesJson);
    const tr = getRowBySpec(style, size, styleNamesJson, sizeNamesJson);
    let rowText = '';
    let inputCount = 0;
    if (tr) {
        const parts = [];
        for (const td of tr.querySelectorAll('td')) {
            if (cellHasDataInput(td)) break;
            const t = normCellText(td);
            if (t) parts.push(t);
        }
        rowText = parts.join(' | ');
        inputCount = rowInputs(tr).length;
    }
    const idx = globalSpecIndex(style, size, ctx.styleNames, ctx.sizeNames);
    return JSON.stringify({
        style: style,
        size: size,
        expectedIdx: idx,
        inStyleList: ctx.styleNames.includes(style),
        inSizeList: ctx.sizeNames.includes(size),
        mapHasEntry: !!mapEntry,
        mapIdx: mapEntry ? mapEntry.idx : null,
        scrollFound: !!(scrollResult && scrollResult.found),
        scrollIdx: scrollResult ? scrollResult.idx : null,
        rowFound: !!tr,
        inputCount: inputCount,
        verifyFilled: tr ? rowHasRequiredValues(tr) : false,
        rowText: rowText.slice(0, 240),
    });
}
return probeStyleSizeRow(
    arguments[0] || '',
    arguments[1] || '',
    arguments[2] || '[]',
    arguments[3] || '[]'
);
"""
)


def _sku_table_debug_snapshot(
    page,
    account_id: str,
    phase: str,
    style_names: list[str] | None,
    size_names: list[str] | None,
) -> dict | None:
    """临时诊断快照；见 _sku_table_debug.py。"""
    if not sku_dbg.enabled() or not style_names or not size_names:
        return None
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    return sku_dbg.log_snapshot(
        page,
        account_id,
        phase,
        _SKU_TABLE_DEBUG_SNAPSHOT_JS,
        styles_json,
        sizes_json,
    )


def _sku_table_debug_probe(
    page,
    account_id: str,
    phase: str,
    style: str,
    size: str,
    style_names: list[str],
    size_names: list[str],
) -> None:
    """单行填表失败时探测 DOM 状态；见 _sku_table_debug.py。"""
    if not sku_dbg.enabled():
        return
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    try:
        raw = page.run_js(
            _SKU_TABLE_DEBUG_PROBE_JS,
            style,
            size,
            styles_json,
            sizes_json,
        ) or "{}"
        probe = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(probe, dict):
            probe = None
    except Exception as exc:
        sku_dbg.log(account_id, phase, "row_probe_error", style=style, size=size, error=str(exc))
        return
    sku_dbg.log_row_probe(account_id, phase, style, size, probe)


def _stamp_global_row_indices(page, style_names: list[str], size_names: list[str]) -> int:
    """虚拟滚动表格：按款式×尺寸逐行滚动并打上全局稳定索引。"""
    if not style_names or not size_names:
        return 0
    expected = len(style_names) * len(size_names)
    try:
        payload_styles = json.dumps(list(style_names), ensure_ascii=False)
        payload_sizes = json.dumps(list(size_names), ensure_ascii=False)
        stamped = int(page.run_js(_STAMP_GLOBAL_ROW_INDICES_JS, payload_styles, payload_sizes) or 0)
        if stamped < expected:
            scroll_stamped = int(
                page.run_js(_STAMP_ROWS_BY_SCROLL_JS, payload_styles, payload_sizes) or 0
            )
            stamped = max(stamped, scroll_stamped)
        return stamped
    except Exception:
        return 0


def _verify_row_filled(
    page,
    index: int,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> bool:
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    try:
        return bool(page.run_js(_VERIFY_ROW_FILLED_JS, str(index), styles_json, sizes_json))
    except Exception:
        return False


def _verify_row_filled_by_spec(
    page,
    style_name: str,
    size_name: str,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> bool:
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    try:
        return bool(
            page.run_js(
                _VERIFY_ROW_FILLED_BY_SPEC_JS,
                style_name,
                size_name,
                styles_json,
                sizes_json,
            )
        )
    except Exception:
        return False


def _spec_order_row_index(
    style_name: str,
    model_name: str,
    style_names: list[str],
    size_names: list[str],
) -> int | None:
    if style_name not in style_names or model_name not in size_names:
        return None
    return style_names.index(style_name) * len(size_names) + size_names.index(model_name)


def _audit_sku_spec_coverage(
    account_id: str,
    skus: list,
    style_names: list[str],
    size_names: list[str],
) -> list[dict]:
    """检查 SKU 与规格矩阵是否一一对应；重复映射会导致某些格永远填不到。"""
    issues: list[dict] = []
    cell_to_skus: dict[tuple[str, str], list] = {}
    for sku in skus:
        style = getattr(sku, "style_name", "") or ""
        size = getattr(sku, "model_name", "") or ""
        if not style or not size:
            continue
        key = (style, size)
        cell_to_skus.setdefault(key, []).append(sku)

    for key, dup in cell_to_skus.items():
        if len(dup) > 1:
            codes = [getattr(s, "combo_folder", "") for s in dup]
            issues.append(
                {
                    "style": key[0],
                    "size": key[1],
                    "reason": "duplicate_sku_mapping",
                    "combo_folders": codes,
                }
            )
            print(
                f"[{account_id}] [警告] 规格 {key[0]} / {key[1]} 对应 {len(dup)} 个 SKU："
                f"{codes}（后填会覆盖前填，其它格可能缺 SKU）",
                flush=True,
            )

    for style in style_names:
        for size in size_names:
            if (style, size) not in cell_to_skus:
                issues.append(
                    {"style": style, "size": size, "reason": "no_sku_for_cell"}
                )
                print(
                    f"[{account_id}] [警告] 规格矩阵 {style} / {size} 无对应 SKU",
                    flush=True,
                )
    return issues


def _count_filled_matrix_cells(
    page,
    style_names: list[str],
    size_names: list[str],
) -> tuple[int, list[dict]]:
    """按页面规格矩阵格计数，而非 SKU 条数。"""
    ok = 0
    empty: list[dict] = []
    for style in style_names:
        for size in size_names:
            if _verify_row_filled_by_spec(
                page, style, size, style_names=style_names, size_names=size_names
            ):
                ok += 1
            else:
                empty.append({"style": style, "size": size, "reason": "matrix_cell_empty"})
    return ok, empty


def _log_price_table_spec_map(
    page,
    account_id: str,
    style_names: list[str],
    size_names: list[str],
) -> None:
    print(
        f"[{account_id}] 录入规格顺序：款式={style_names} | 尺寸={size_names}",
        flush=True,
    )
    try:
        styles_json, sizes_json = _spec_lists_json(style_names, size_names)
        raw = page.run_js(_DUMP_STYLE_SIZE_MAP_JS, styles_json, sizes_json) or "[]"
        rows = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(rows, list):
            print(f"[{account_id}] 价格表页面读到的规格行（共 {len(rows)} 行）：", flush=True)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                print(
                    f"[{account_id}]   行#{int(row.get('idx', -1)) + 1} "
                    f"{row.get('style', '')} / {row.get('size', '')}",
                    flush=True,
                )
            sku_dbg.log_spec_map(account_id, "price_table_spec_map", rows)
    except Exception as exc:
        print(f"[{account_id}] 价格表规格行读取失败：{_safe_exc(exc)}", flush=True)


def _fill_skus_by_spec_order(
    page,
    account_id: str,
    skus: list,
    style_names: list[str],
    size_names: list[str],
    defaults: dict,
) -> tuple[int, list[dict]]:
    """按录入规格顺序（款式×尺寸）用行号填表，与预览图索引一致。"""
    ok = 0
    failed: list[dict] = []
    probe_budget = 5
    print(
        f"[{account_id}] 填表策略：按录入顺序索引（{len(style_names)} 款 × {len(size_names)} 尺寸）",
        flush=True,
    )
    for sku in skus:
        label = f"{sku.style_name} / {sku.model_name}"
        idx = _spec_order_row_index(sku.style_name, sku.model_name, style_names, size_names)
        if idx is None:
            print(
                f"[{account_id}]  填表跳过：{label}（不在录入规格列表中）编码={sku.combo_folder}",
                flush=True,
            )
            failed.append(
                {
                    "style": sku.style_name,
                    "size": sku.model_name,
                    "reason": "index_not_found",
                }
            )
            continue
        row_data = {
            "inventory": getattr(sku, "inventory", None) or defaults.get("inventory", "10"),
            "group_price": getattr(sku, "group_price", None) or defaults.get("group_price", "199.9"),
            "single_price": getattr(sku, "single_price", None) or defaults.get("single_price", "299.9"),
            "sku_code": sku.combo_folder,
        }
        print(
            f"[{account_id}]  填表行 #{idx + 1} ← {label} | 编码={sku.combo_folder} | "
            f"库存={row_data['inventory']} 拼团={row_data['group_price']} 单买={row_data['single_price']}",
            flush=True,
        )
        success = _fill_row_by_style_size(
            page,
            sku.style_name,
            sku.model_name,
            row_data,
            style_names=style_names,
            size_names=size_names,
        )
        if success:
            success = _verify_row_filled_by_spec(
                page,
                sku.style_name,
                sku.model_name,
                style_names=style_names,
                size_names=size_names,
            )
        if success:
            ok += 1
            print(f"[{account_id}]    → 文字字段填写成功", flush=True)
        else:
            print(f"[{account_id}]    → 文字字段填写失败（行无输入框或 JS 填值失败）", flush=True)
            failed.append(
                {
                    "style": sku.style_name,
                    "size": sku.model_name,
                    "reason": "fill_by_index_failed",
                }
            )
            if probe_budget > 0:
                _sku_table_debug_probe(
                    page,
                    account_id,
                    "spec_order_fail",
                    sku.style_name,
                    sku.model_name,
                    style_names,
                    size_names,
                )
                probe_budget -= 1
    matrix_need = len(style_names) * len(size_names)
    matrix_ok, matrix_empty = _count_filled_matrix_cells(page, style_names, size_names)
    if matrix_empty:
        for item in matrix_empty:
            if not any(
                f.get("style") == item["style"] and f.get("size") == item["size"]
                for f in failed
            ):
                failed.append(item)
        print(
            f"[{account_id}] 矩阵校验：{matrix_ok}/{matrix_need} 格已填，"
            f"未填 {[f'{x['style']}/{x['size']}' for x in matrix_empty]}",
            flush=True,
        )
    return matrix_ok, failed


def _sku_fill_items(skus: list, defaults: dict) -> list[dict]:
    return [
        {
            "style": getattr(sku, "style_name", "") or "",
            "size": getattr(sku, "model_name", "") or "",
            "vals": [
                str(getattr(sku, "inventory", None) or defaults.get("inventory", "10")),
                str(getattr(sku, "group_price", None) or defaults.get("group_price", "199.9")),
                str(getattr(sku, "single_price", None) or defaults.get("single_price", "299.9")),
                sku.combo_folder,
            ],
        }
        for sku in skus
    ]


def _fill_skus_by_style_size(
    page,
    skus: list,
    defaults: dict,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> tuple[int, list[dict]]:
    """按「款式+尺寸」定位行并填写，返回 (成功数, 失败列表)。"""
    payload = json.dumps(_sku_fill_items(skus, defaults), ensure_ascii=False)
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    try:
        raw = page.run_js(_FILL_SKUS_BY_STYLE_SIZE_JS, payload, styles_json, sizes_json) or "{}"
        result = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(result, dict):
            return 0, []
        return int(result.get("ok") or 0), list(result.get("failed") or [])
    except Exception:
        return 0, []


def _diagnose_fill_state(
    page,
    account_id: str,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
):
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    try:
        raw = page.run_js(_DIAGNOSE_FILL_JS, styles_json, sizes_json) or "{}"
        info = json.loads(raw) if isinstance(raw, str) else raw
        print(
            f"[{account_id}] 填表诊断：表格行={info.get('tableRows')} "
            f"标记行={info.get('markedRows')} 规格标记={info.get('specMarkedRows')} "
            f"数据行={info.get('dataRows')} 首行输入框={info.get('inputsInFirst')}",
            flush=True,
        )
        if isinstance(info, dict):
            sku_dbg.log_diagnose(account_id, "fill_state", info)
    except Exception as exc:
        print(f"[{account_id}] 填表诊断失败：{_safe_exc(exc)}", flush=True)


def _fill_all_rows_batch(
    page,
    skus: list,
    defaults: dict,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> int:
    """一次 JS 填完所有行的库存/价格/编码（参数用 JSON 传递）。"""
    filled, _failed = _fill_skus_by_style_size(
        page,
        skus,
        defaults,
        style_names=style_names,
        size_names=size_names,
    )
    return filled


def _fill_rows_mapped_batch(
    page,
    skus: list,
    row_indices: list[int],
    defaults: dict,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> int:
    """按「款式+尺寸」一次 JS 填完（row_indices 仅用于预览图，填表以 style+size 为准）。"""
    filled, _failed = _fill_skus_by_style_size(
        page,
        skus,
        defaults,
        style_names=style_names,
        size_names=size_names,
    )
    return filled


def _scroll_spec_row_into_view(
    page,
    style_name: str,
    size_name: str,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> bool:
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    try:
        raw = page.run_js(
            _SCROLL_FIND_STYLE_SIZE_ROW_JS,
            style_name,
            size_name,
            styles_json,
            sizes_json,
        ) or "{}"
        result = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(result, dict) and result.get("found"):
            time.sleep(0.12)
            return True
    except Exception:
        pass
    return False


def _fill_row_by_style_size(
    page,
    style_name: str,
    size_name: str,
    row_data: dict,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> bool:
    vals = json.dumps(
        [
            str(row_data.get("inventory", "")),
            str(row_data.get("group_price", "")),
            str(row_data.get("single_price", "")),
            str(row_data.get("sku_code", "")),
        ],
        ensure_ascii=False,
    )
    styles_json, sizes_json = _spec_lists_json(style_names, size_names)
    try:
        _scroll_spec_row_into_view(
            page,
            style_name,
            size_name,
            style_names=style_names,
            size_names=size_names,
        )
        count = page.run_js(
            _FILL_ONE_BY_STYLE_SIZE_JS,
            style_name,
            size_name,
            vals,
            styles_json,
            sizes_json,
        ) or 0
        return count >= 4
    except Exception:
        return False


def _compute_row_indices(
    skus: list,
    marked_rows: list | None = None,
    page=None,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> list[int]:
    """按款式+尺寸匹配价格表行索引。"""
    if page is not None:
        pairs = [
            {
                "style": getattr(sku, "style_name", "") or "",
                "size": getattr(sku, "model_name", "") or "",
            }
            for sku in skus
        ]
        styles_json, sizes_json = _spec_lists_json(style_names, size_names)
        try:
            raw = page.run_js(
                _BUILD_STYLE_SIZE_ROW_MAP_JS,
                json.dumps(pairs, ensure_ascii=False),
                styles_json,
                sizes_json,
            )
            if raw:
                indices = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(indices, list) and len(indices) == len(skus):
                    return [int(i) for i in indices]
        except Exception:
            pass
    if not marked_rows:
        return list(range(len(skus)))
    row_map = _sku_row_index_from_rows(marked_rows)
    indices: list[int] = []
    for i, sku in enumerate(skus):
        style_name = getattr(sku, "style_name", "") or ""
        size_name = getattr(sku, "model_name", "") or ""
        row = row_map.get((style_name, size_name)) if style_name and size_name else None
        if row is not None:
            marked = row.attr(_SKU_ROW_ATTR)
            if marked is not None and str(marked).isdigit():
                indices.append(int(marked))
                continue
            for row_idx, candidate in enumerate(marked_rows):
                if candidate == row:
                    indices.append(row_idx)
                    break
            else:
                indices.append(i)
        else:
            indices.append(i)
    return indices


def _resolve_sku_row_index(page, skus: list, index: int, rows: list | None = None) -> int:
    """按款式+尺寸匹配价格表行；匹配失败时回退到顺序索引。"""
    if index >= len(skus):
        return index
    if rows is None:
        rows = _sku_price_table_rows(page, scroll=False)
    indices = _compute_row_indices(skus, rows, page=page)
    return indices[index]


def _unique_sku_spec_pairs(skus: list) -> int:
    return len(
        {
            (getattr(sku, "style_name", "") or "", getattr(sku, "model_name", "") or "")
            for sku in skus
        }
    )


def _prefer_style_size_fill(
    style_names: list[str] | None,
    size_names: list[str] | None,
) -> bool:
    """
    单款式（1 x N）场景，优先按「款式+尺寸」定位，规避偶发行序错位。
    多款式保持原有按顺序索引策略。
    """
    if not style_names or not size_names:
        return True
    return len(style_names) <= 1


def fill_multi_spec_rows(
    page,
    account_id: str,
    skus: list,
    defaults: dict,
    rows: list | None = None,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
) -> bool:
    """先批量填文字字段，再逐个上传预览图。返回预览图是否全部就绪。"""
    total_start = _now()
    unique_rows = _unique_sku_spec_pairs(skus)

    if not rows:
        t = _now()
        _scroll_sku_table_to_load(
            page,
            unique_rows,
            style_names=style_names,
            size_names=size_names,
        )
        rows = _sku_price_table_rows(page)
        _log_step(account_id, f"定位价格表 {len(rows)} 行", t)
    else:
        _scroll_sku_table_to_load(
            page,
            unique_rows,
            style_names=style_names,
            size_names=size_names,
        )

    print(
        f"[{account_id}] 开始填写 {len(skus)} 个 SKU（已定位 {len(rows)} 行，"
        f"唯一规格 {unique_rows}）",
        flush=True,
    )

    t = _now()
    matrix_need = (
        len(style_names) * len(size_names)
        if style_names and size_names
        else unique_rows
    )
    for warm in range(3):
        loaded = _count_loaded_spec_rows(
            page,
            matrix_need,
            style_names=style_names,
            size_names=size_names,
        )
        if loaded >= matrix_need:
            break
        if warm < 2:
            _click_blank_area(page)
            if style_names and size_names:
                _activate_spec_price_table(
                    page, style_names, size_names, account_id=account_id
                )
            time.sleep(0.8)
    if style_names and size_names:
        stamped = _stamp_global_row_indices(page, style_names, size_names)
        if stamped:
            print(
                f"[{account_id}] 虚拟表格已标记 {stamped}/{matrix_need} 行规格索引",
                flush=True,
            )
        elif matrix_need:
            print(
                f"[{account_id}] 虚拟表格标记不足 {stamped}/{matrix_need}，将按滚动顺序填表",
                flush=True,
            )
        _sku_table_debug_snapshot(
            page, account_id, "after_stamp", style_names, size_names
        )
    time.sleep(0.35)
    _log_price_table_spec_map(page, account_id, style_names or [], size_names or [])
    _sku_table_debug_snapshot(
        page, account_id, "before_fill", style_names, size_names
    )
    _audit_sku_spec_coverage(account_id, skus, style_names, size_names)

    t = _now()
    use_style_size_fill = _prefer_style_size_fill(style_names, size_names)
    if style_names and size_names and not use_style_size_fill:
        filled, failed = _fill_skus_by_spec_order(
            page, account_id, skus, style_names, size_names, defaults
        )
    else:
        filled, failed = _fill_skus_by_style_size(
            page,
            skus,
            defaults,
            style_names=style_names,
            size_names=size_names,
        )
    if failed:
        sku_dbg.log_fill_failures(account_id, "spec_order", failed)
        for item in failed:
            print(
                f"[{account_id}] 按序填表未命中：{item.get('style')} / {item.get('size')} "
                f"({item.get('reason')})",
                flush=True,
            )
    strategy_label = "文字定位" if use_style_size_fill else "按序索引"
    _log_step(account_id, f"{strategy_label}填写库存/价格/编码 {filled}/{matrix_need} 格", t)
    sku_dbg.log_fill_progress(
        account_id,
        "after_spec_order",
        filled=filled,
        total=matrix_need,
        failed_count=len(failed),
    )

    if failed:
        t = _now()
        text_filled, text_failed = _fill_skus_by_style_size(
            page,
            skus,
            defaults,
            style_names=style_names,
            size_names=size_names,
        )
        if text_failed:
            sku_dbg.log_fill_failures(account_id, "style_size_retry", text_failed)
            for item in text_failed:
                print(
                    f"[{account_id}] 文字匹配补填未命中：{item.get('style')} / {item.get('size')} "
                    f"({item.get('reason')})",
                    flush=True,
                )
        if text_filled > filled:
            filled = text_filled
        filled, matrix_empty = _count_filled_matrix_cells(page, style_names, size_names)
        if matrix_empty:
            failed = matrix_empty
        _log_step(account_id, f"文字匹配补填后 {filled}/{matrix_need} 格", t)

    row_indices = (
        [
            _spec_order_row_index(s.style_name, s.model_name, style_names, size_names)
            if style_names and size_names
            else None
            for s in skus
        ]
    )
    if style_names and size_names:
        row_indices = [i if i is not None else j for j, i in enumerate(row_indices)]
    else:
        row_indices = _compute_row_indices(
            skus,
            rows,
            page=page,
            style_names=style_names,
            size_names=size_names,
        )
    _log_step(account_id, "匹配价格表行索引", t)

    if failed or filled < matrix_need:
        _diagnose_fill_state(
            page,
            account_id,
            style_names=style_names,
            size_names=size_names,
        )
        _sku_table_debug_snapshot(
            page, account_id, "fill_incomplete", style_names, size_names
        )
        failed_keys = {(f.get("style"), f.get("size")) for f in failed}
        retry_skus = [
            sku
            for sku in skus
            if (sku.style_name, sku.model_name) in failed_keys
        ]
        for sku in retry_skus:
            label = f"{sku.style_name} / {sku.model_name}"
            row_data = {
                "inventory": getattr(sku, "inventory", None) or defaults.get("inventory", "10"),
                "group_price": getattr(sku, "group_price", None) or defaults.get("group_price", "199.9"),
                "single_price": getattr(sku, "single_price", None) or defaults.get("single_price", "299.9"),
                "sku_code": sku.combo_folder,
            }
            try:
                t = _now()
                ok = _fill_row_by_style_size(
                    page,
                    sku.style_name,
                    sku.model_name,
                    row_data,
                    style_names=style_names,
                    size_names=size_names,
                )
                if ok:
                    ok = _verify_row_filled_by_spec(
                        page,
                        sku.style_name,
                        sku.model_name,
                        style_names=style_names,
                        size_names=size_names,
                    )
                if ok:
                    _log_step(account_id, f"补填 {label}", t)
                else:
                    print(f"[{account_id}] 补填失败：{label}", flush=True)
            except Exception as exc:
                print(f"[{account_id}] 补填异常 [{label}]：{_safe_exc(exc)}", flush=True)
        for style, size in failed_keys:
            if any(s.style_name == style and s.model_name == size for s in skus):
                continue
            print(
                f"[{account_id}] 补填跳过：{style} / {size}（无对应 SKU，请检查槽位对齐）",
                flush=True,
            )
        if style_names and size_names:
            filled, failed = _count_filled_matrix_cells(page, style_names, size_names)
        _log_step(account_id, f"补填后合计 {filled}/{matrix_need} 格（已校验）", t)
        sku_dbg.log_fill_progress(
            account_id,
            "after_retry",
            filled=filled,
            total=matrix_need,
            failed_count=len(failed),
        )
        _sku_table_debug_snapshot(
            page, account_id, "after_retry", style_names, size_names
        )

    if filled < matrix_need:
        sku_dbg.log(
            account_id,
            "fill_summary",
            "仍有未填完规格格",
            filled=filled,
            total=matrix_need,
            gap=matrix_need - filled,
        )
        _sku_table_debug_snapshot(
            page, account_id, "fill_final", style_names, size_names
        )

    print(f"[{account_id}] 文字字段填完，开始上传预览图...", flush=True)
    t = _now()
    _scroll_sku_table_to_load(
        page,
        len(skus),
        style_names=style_names,
        size_names=size_names,
    )
    if style_names and size_names:
        _stamp_global_row_indices(page, style_names, size_names)
    preview_count = _mark_preview_inputs(page)
    _log_step(account_id, f"预览图上传位 {preview_count} 个（虚拟滚动下可能少于 SKU 数）", t)

    uploaded = 0
    need_upload = len(
        {
            (sku.style_name or "", sku.model_name or "")
            for sku in skus
            if sku.preview_image
        }
    )
    for i, sku in enumerate(skus):
        label = f"{sku.style_name} / {sku.model_name}"
        row_idx = (
            _spec_order_row_index(sku.style_name, sku.model_name, style_names, size_names)
            if style_names and size_names
            else (row_indices[i] if i < len(row_indices) else i)
        )
        if row_idx is None:
            row_idx = i
        if sku.style_name and sku.model_name:
            found_idx = _ensure_style_size_row_visible(
                page,
                sku.style_name,
                sku.model_name,
                style_names=style_names,
                size_names=size_names,
            )
            if found_idx is not None and not (style_names and size_names):
                row_idx = found_idx
        if not sku.preview_image:
            continue
        sku_start = _now()
        print(f"[{account_id}] >>> 预览图 {i + 1}/{len(skus)}：{label}", flush=True)
        try:
            if upload_row_preview(
                page,
                row_idx,
                str(sku.preview_image.resolve()),
                account_id,
                label,
                style_name=sku.style_name or "",
                size_name=sku.model_name or "",
                style_names=style_names,
                size_names=size_names,
            ):
                uploaded += 1
        except Exception as exc:
            err = _safe_exc(exc)
            if "连接已断开" in err or "disconnect" in err.lower():
                raise
            print(f"[{account_id}] 预览图异常 [{label}]：{err}", flush=True)
        _log_step(account_id, f"SKU {i + 1} 整行合计（含预览图）", sku_start)

    verified = 0
    seen_keys: set[tuple[str, str]] = set()
    for i, sku in enumerate(skus):
        if not sku.preview_image:
            continue
        key = (sku.style_name or "", sku.model_name or "")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        row_idx = row_indices[i] if i < len(row_indices) else i
        found_idx = _ensure_style_size_row_visible(
            page,
            key[0],
            key[1],
            style_names=style_names,
            size_names=size_names,
        )
        if found_idx is not None:
            row_idx = found_idx
        if _preview_is_uploaded(
            page,
            row_idx,
            style_name=key[0],
            size_name=key[1],
            style_names=style_names,
            size_names=size_names,
        ):
            verified += 1
    print(
        f"[{account_id}] 预览图结果：上传成功 {uploaded}/{need_upload}，"
        f"页面校验 {verified}/{need_upload}",
        flush=True,
    )
    if verified < need_upload:
        print(f"[{account_id}] [警告] 仍有预览图未上传，提交可能失败", flush=True)

    _log_step(account_id, f"全部 {len(skus)} 个 SKU 流程合计", total_start)
    return {
        "previews_ok": verified >= need_upload,
        "price_filled": filled,
        "price_total": len(skus),
        "price_failed": failed,
        "preview_uploaded": uploaded,
        "preview_need": need_upload,
        "preview_verified": verified,
    }

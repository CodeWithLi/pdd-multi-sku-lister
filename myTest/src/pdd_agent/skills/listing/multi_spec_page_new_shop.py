"""新店铺规格录入：先点「添加规格类型」再选下拉维度，再填规格值。

与 ``multi_spec_page.add_style_and_model_specs``（旧店铺直接出现规格组）并列；
由 ``add_style_and_model_specs_auto`` 按页面 DOM 自动分流。
"""

from __future__ import annotations

import json
import time

from pdd_agent.skills.listing.multi_spec_page import (
    _activate_spec_price_table,
    _click_blank_area,
    _inputs_in_box,
    _react_fill_spec_input,
    _select_spec_type,
    _spec_row_boxes,
    _wait_inputs_count,
    _wait_spec_matrix_rows,
    add_style_and_model_specs,
)

_DETECT_NEW_SHOP_SPEC_UI_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
const spec = document.querySelector('#spec');
if (!spec) return { isNew: false, reason: 'no_spec' };

const oldBoxes = spec.querySelectorAll('.goods-spec-row-box');
if (oldBoxes.length > 0) {
    return { isNew: false, reason: 'old_row_box', oldBoxes: oldBoxes.length };
}

let addBtnText = '';
let hasAddBtn = false;
for (const btn of spec.querySelectorAll('button')) {
    const t = (btn.innerText || btn.textContent || '').replace(/\\s+/g, '');
    if (t.includes('添加规格类型') && isVisible(btn)) {
        hasAddBtn = true;
        addBtnText = (btn.innerText || btn.textContent || '').trim();
        break;
    }
}
if (!hasAddBtn) return { isNew: false, reason: 'no_add_btn' };

const hasWrapper = !!spec.querySelector(
    '.goods-spec-wrapper, .goods-sku-box.goods-spec-wrapper'
);
const items = spec.querySelectorAll('.goods-spec-item');
const blockCount = (function() {
    let n = 0;
    for (const el of spec.querySelectorAll('.goods-spec-item, .goods-spec-row-box')) {
        if (isVisible(el)) n++;
    }
    if (n) return n;
    const wrapper = spec.querySelector('.goods-spec-wrapper, .goods-sku-box.goods-spec-wrapper');
    if (!wrapper) return 0;
    for (const el of wrapper.children) {
        if (!isVisible(el) || el.tagName === 'BUTTON') continue;
        if ((el.className || '').toString().includes('goods-spec-tips')) continue;
        const text = (el.innerText || '').replace(/\\s+/g, '');
        if (text.includes('添加规格类型') || text.includes('AI添加规格')) continue;
        if (el.querySelector('input[placeholder*="规格"], [class*="select"], .ant-select')) n++;
    }
    return n;
})();

if (hasWrapper || blockCount === 0) {
    return {
        isNew: true,
        reason: hasWrapper ? 'wrapper' : 'add_btn_no_blocks',
        itemCount: items.length,
        blockCount,
        addBtnText,
        hasWrapper,
    };
}
return { isNew: false, reason: 'unknown', itemCount: items.length, blockCount };
"""

_SPEC_DOM_CORE_JS = """
function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function getSpecRoot() {
    return document.querySelector('#spec');
}
function getAddBtnMeta(spec) {
    spec = spec || getSpecRoot();
    if (!spec) return { text: '', current: 0, max: 2 };
    for (const btn of spec.querySelectorAll('button')) {
        const raw = (btn.innerText || btn.textContent || '').trim();
        const compact = raw.replace(/\\s+/g, '');
        if (!compact.includes('添加规格类型') || !isVisible(btn)) continue;
        const m = compact.match(/添加规格类型\\((\\d+)\\/(\\d+)\\)/);
        return {
            text: raw,
            current: m ? parseInt(m[1], 10) : 0,
            max: m ? parseInt(m[2], 10) : 2,
        };
    }
    return { text: '', current: 0, max: 2 };
}
function isTypeDimensionLabel(text) {
    const t = (text || '').replace(/\\s+/g, '').replace(/常用/g, '');
    if (/^规格类型\\d*$/.test(t)) return true;
    const keys = ['颜色', '款式', '尺寸', '型号', '套餐', '规格', '器型', '材质', '容量', '色号'];
    return keys.some((k) => t === k || t.startsWith(k));
}
function dispatchClick(el) {
    if (!el) return;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    try {
        el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
        el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    } catch (e) {}
}
function isBeastTypeSelect(sel) {
    if (!sel) return false;
    const raw = (sel.innerText || sel.textContent || '').trim();
    const compact = raw.replace(/\\s+/g, '');
    const header = sel.querySelector('[data-testid="beast-core-select-header"]');
    const headerText = (header?.innerText || header?.textContent || raw).trim();
    const hCompact = headerText.replace(/\\s+/g, '');
    if (isTypeDimensionLabel(hCompact.split(/\\s+/)[0])) return true;
    if (/^规格类型\\d*$/.test(hCompact) || hCompact.includes('规格类型')) return true;
    if (hCompact.includes('请选择或输入规格类型')) return true;
    const input = sel.querySelector('input');
    const ph = (input?.placeholder || '').trim();
    if (/规格类型/.test(ph) || ph.includes('请选择或输入规格类型')) return true;
    return compact.includes('规格类型') || compact.includes('请选择或输入规格类型');
}
function collectBeastSelectTriggers(spec) {
    spec = spec || getSpecRoot();
    if (!spec) return [];
    const out = [];
    for (const sel of spec.querySelectorAll('[data-testid="beast-core-select"]')) {
        if (!isVisible(sel) || !isBeastTypeSelect(sel)) continue;
        const header = sel.querySelector('[data-testid="beast-core-select-header"]');
        const pointer = sel.querySelector('[class*="pointerCell"], [class*="IPT_pointerCell"]');
        const suffix = sel.querySelector('[class*="suffixCell"], [class*="IPT_suffixCell"]');
        const trigger = pointer || suffix || header || sel;
        const raw = (sel.innerText || sel.textContent || '').trim();
        const headerText = (header?.innerText || header?.textContent || raw).trim();
        out.push({
            el: trigger,
            selectEl: sel,
            top: sel.getBoundingClientRect().top,
            text: headerText.split(/\\s+/)[0] || raw.split(/\\s+/)[0] || '',
            raw: raw.slice(0, 60),
        });
    }
    out.sort((a, b) => a.top - b.top);
    const unique = [];
    for (const item of out) {
        if (unique.some((u) => Math.abs(u.top - item.top) < 28)) continue;
        unique.push(item);
    }
    return unique;
}
function collectAllTypeDropdownTriggers(spec) {
    spec = spec || getSpecRoot();
    if (!spec) return [];
    const all = [];
    for (const item of collectTypeDropdownCandidates(spec)) {
        all.push({
            el: item.el,
            top: item.top,
            text: item.text,
            raw: item.raw,
            method: 'ant',
            selectEl: null,
        });
    }
    for (const item of collectBeastSelectTriggers(spec)) {
        all.push({
            el: item.el,
            top: item.top,
            text: item.text,
            raw: item.raw,
            method: 'beast',
            selectEl: item.selectEl,
        });
    }
    all.sort((a, b) => a.top - b.top);
    const unique = [];
    for (const item of all) {
        const idx = unique.findIndex((u) => Math.abs(u.top - item.top) < 20);
        if (idx >= 0) {
            if (item.method === 'beast') unique[idx] = item;
            continue;
        }
        unique.push(item);
    }
    return unique;
}
function openSpecTypeDropdownByIndex(index) {
    const spec = getSpecRoot();
    if (!spec) return { ok: false, reason: 'no_spec' };
    const triggers = collectAllTypeDropdownTriggers(spec);
    const item = triggers[index];
    if (!item) {
        return {
            ok: false,
            reason: 'no_trigger',
            index,
            triggerCount: triggers.length,
            secondRowVisible: secondSpecRowVisible(spec),
        };
    }
    let clickEl = item.el;
    const sel = item.selectEl || item.el.closest('[data-testid="beast-core-select"]');
    if (item.method === 'beast' || sel) {
        clickEl = sel?.querySelector('[data-testid="beast-core-select-header"]')
            || sel?.querySelector('[class*="pointerCell"], [class*="IPT_pointerCell"]')
            || sel?.querySelector('[class*="suffixCell"], [class*="IPT_suffixCell"]')
            || clickEl;
    }
    dispatchClick(clickEl);
    return {
        ok: true,
        method: item.method,
        index,
        triggerCount: triggers.length,
        text: item.text,
        raw: item.raw,
    };
}
function countTypeDropdownTriggers(spec) {
    return collectAllTypeDropdownTriggers(spec).length;
}
function collectTypeDropdownCandidates(spec) {
    spec = spec || getSpecRoot();
    if (!spec) return [];
    const out = [];
    for (const el of spec.querySelectorAll(
        '.ant-select-selector, [class*="select-selector"], [class*="Select"][class*="selector"]'
    )) {
        if (!isVisible(el) || el.closest('button')) continue;
        const raw = (el.innerText || el.textContent || '').trim();
        const t = raw.split(/\\s+/)[0];
        if (!isTypeDimensionLabel(t) && !/^规格类型\\d*$/.test(t)) continue;
        out.push({
            el: el,
            top: el.getBoundingClientRect().top,
            text: t,
            raw: raw.slice(0, 60),
        });
    }
    out.sort((a, b) => a.top - b.top);
    const unique = [];
    for (const item of out) {
        if (unique.some((u) => Math.abs(u.top - item.top) < 15)) continue;
        unique.push(item);
    }
    return unique;
}
function secondSpecRowVisible(spec) {
    spec = spec || getSpecRoot();
    if (!spec) return false;
    const text = spec.innerText || spec.textContent || '';
    if (text.includes('规格类型2') || text.includes('请先选择规格类型2')) return true;
    if (text.includes('请选择或输入规格类型')) return true;
    return false;
}
function countSpecTypeSlots(spec) {
    spec = spec || getSpecRoot();
    if (!spec) return 0;
    const meta = getAddBtnMeta(spec);
    const byDropdown = countTypeDropdownTriggers(spec);
    if (secondSpecRowVisible(spec)) {
        return Math.max(2, byDropdown, meta.current);
    }
    if (meta.text && meta.text.includes('添加规格类型')) {
        return Math.max(meta.current, byDropdown);
    }
    let byDelete = 0;
    const seenTops = new Set();
    for (const el of spec.querySelectorAll('a, span, button')) {
        const t = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
        if (!t.includes('删除规格') || !isVisible(el)) continue;
        const top = Math.round(el.getBoundingClientRect().top / 20);
        if (seenTops.has(top)) continue;
        seenTops.add(top);
        byDelete++;
    }
    return Math.max(byDropdown, Math.min(byDelete, 2));
}
function hasSpecTypeSlot(spec, index) {
    const needed = index + 1;
    const meta = getAddBtnMeta(spec);
    const byDropdown = countTypeDropdownTriggers(spec);
    if (index >= 1 && secondSpecRowVisible(spec)) return true;
    if (meta.text && meta.text.includes('添加规格类型') && meta.current < needed) {
        return false;
    }
    if (byDropdown >= needed) return true;
    if (meta.text && meta.current >= needed) return true;
    return false;
}
function findTypeDropdownByIndex(spec, index) {
    spec = spec || getSpecRoot();
    if (!spec) return null;
    const triggers = collectAllTypeDropdownTriggers(spec);
    return triggers[index] ? triggers[index].el : null;
}
function findSpecTypeRows(spec) {
    spec = spec || getSpecRoot();
    if (!spec) return [];
    return collectAllTypeDropdownTriggers(spec).map((item) => {
        let row = item.selectEl?.closest('.goods-spec-row-box, .goods-spec-item');
        if (!row && item.el) {
            row = item.el.closest('.goods-spec-row-box, .goods-spec-item');
        }
        if (!row && item.el) {
            row = item.el.parentElement;
            for (let i = 0; i < 12 && row && row !== spec; i++) {
                const rt = (row.innerText || row.textContent || '').replace(/\\s+/g, ' ');
                if (/删除规格/.test(rt.replace(/\\s+/g, ''))) break;
                row = row.parentElement;
            }
        }
        return row || item.el;
    });
}
function findTypeDropdownInRow(row) {
    if (!row) return null;
    const selectors = [...row.querySelectorAll(
        '.ant-select-selector, [class*="select-selector"], [class*="Select"][class*="selector"], '
        + '[data-testid="beast-core-select-header"], [class*="pointerCell"], [class*="IPT_pointerCell"]'
    )].filter(isVisible);
    for (const el of selectors) {
        const t = (el.innerText || el.textContent || '').trim().split(/\\s+/)[0];
        if (isTypeDimensionLabel(t)) return el;
    }
    for (const el of selectors) {
        const t = (el.innerText || el.textContent || '').trim();
        if (/规格类型/.test(t)) return el;
    }
    return selectors[0] || null;
}
function findSpecTypeDropdownTriggers(spec) {
    spec = spec || getSpecRoot();
    if (!spec) return [];
    return collectAllTypeDropdownTriggers(spec).map((item) => ({
        el: item.el,
        method: item.method || 'type_by_position',
        text: item.text,
        top: item.top,
        raw: item.raw,
        selectEl: item.selectEl,
    }));
}
function inferSpecTypeCount(spec) {
    return countSpecTypeSlots(spec);
}
function findSpecValueInputs(spec, typeIndex) {
    spec = spec || getSpecRoot();
    if (!spec) return [];
    const candidates = collectAllTypeDropdownTriggers(spec);
    const cur = candidates[typeIndex];
    const next = candidates[typeIndex + 1];
    if (!cur && typeIndex >= 1 && secondSpecRowVisible(spec)) {
        const all = [...spec.querySelectorAll(
            'input[placeholder*="规格名称"], input[placeholder*="规格"], '
            + 'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"]'
        )].filter(isVisible);
        const firstInputs = findSpecValueInputs(spec, 0);
        const firstBottom = firstInputs.length
            ? Math.max(...firstInputs.map((el) => el.getBoundingClientRect().bottom))
            : 0;
        const secondInputs = all.filter((el) => el.getBoundingClientRect().top >= firstBottom - 8);
        if (secondInputs.length) return secondInputs;
        if (all.length > 1) return all.slice(1);
    }
    if (!cur) {
        const all = [...spec.querySelectorAll(
            'input[placeholder*="规格名称"], input[placeholder*="规格"], '
            + 'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"]'
        )].filter(isVisible);
        if (typeIndex < all.length) return [all[typeIndex]];
        return all.length ? [all[all.length - 1]] : [];
    }
    const top = cur.top - 8;
    const bottom = next ? next.top - 8 : 99999;
    const inputs = [...spec.querySelectorAll(
        'input[placeholder*="规格名称"], input[placeholder*="规格"], '
        + 'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"]'
    )].filter((el) => {
        if (!isVisible(el)) return false;
        const t = el.getBoundingClientRect().top;
        return t >= top && t < bottom;
    });
    if (inputs.length) return inputs;
    const row = findSpecTypeRows(spec)[typeIndex];
    if (row) {
        const rowInputs = [...row.querySelectorAll(
            'input[placeholder*="规格名称"], input[placeholder*="规格"], '
        + 'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"]'
        )].filter(isVisible);
        if (rowInputs.length) return rowInputs;
    }
    const all = [...spec.querySelectorAll(
        'input[placeholder*="规格名称"], input[placeholder*="规格"], '
        + 'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"]'
    )].filter(isVisible);
    if (typeIndex < all.length) return [all[typeIndex]];
    return all.length ? [all[all.length - 1]] : [];
}
function isFirstSpecConfigured(spec) {
    spec = spec || getSpecRoot();
    if (!spec) return false;
    const triggers = collectAllTypeDropdownTriggers(spec);
    if (!triggers.length) return false;
    const first = triggers[0];
    const text = (first.text || first.raw || '').replace(/\\s+/g, '');
    if (/^规格类型\\d*$/.test(text) || text.includes('请选择或输入规格类型')) return false;
    const typeOk = ['颜色', '款式'].some((k) => text === k || text.startsWith(k));
    if (!typeOk) return false;
    const inputs = findSpecValueInputs(spec, 0);
    if (!inputs.length) return false;
    return inputs.some((inp) => ((inp.value || inp.textContent || '').trim().length > 0));
}
"""

_SNAPSHOT_SPEC_DOM_JS = (
    _SPEC_DOM_CORE_JS
    + """
const spec = getSpecRoot();
if (!spec) return { ok: false, reason: 'no_spec' };
const addMeta = getAddBtnMeta(spec);
const triggers = findSpecTypeDropdownTriggers(spec);
const slotCount = countSpecTypeSlots(spec);
return {
    ok: true,
    addBtnText: addMeta.text,
    addBtnCurrent: addMeta.current,
    addBtnMax: addMeta.max,
    specTypeRowCount: slotCount,
    specTypeSlotCount: slotCount,
    dropdownCount: triggers.length,
    dropdowns: triggers.map((t) => ({ method: t.method, text: t.text, top: t.top, raw: t.raw })),
    inferredCount: slotCount,
    secondRowVisible: secondSpecRowVisible(spec),
    specItems: spec.querySelectorAll('.goods-spec-item').length,
    hasWrapper: !!spec.querySelector('.goods-spec-wrapper, .goods-sku-box.goods-spec-wrapper'),
    bodyHasSpec: (document.body.innerText || '').includes('商品规格'),
    oldRowBoxes: spec.querySelectorAll('.goods-spec-row-box').length,
};
"""
)

_SCROLL_SPEC_INTO_VIEW_JS = (
    _SPEC_DOM_CORE_JS
    + """
const spec = getSpecRoot();
if (spec) spec.scrollIntoView({ block: 'center', behavior: 'instant' });
const meta = getAddBtnMeta(spec);
for (const btn of spec ? spec.querySelectorAll('button') : []) {
    const t = (btn.innerText || btn.textContent || '').replace(/\\s+/g, '');
    if (t.includes('添加规格类型')) {
        btn.scrollIntoView({ block: 'center', behavior: 'instant' });
        break;
    }
}
return !!spec;
"""
)

_GET_SPEC_TYPE_COUNT_JS = (
    _SPEC_DOM_CORE_JS + "return countSpecTypeSlots(getSpecRoot());"
)

_HAS_SPEC_TYPE_SLOT_JS = (
    _SPEC_DOM_CORE_JS
    + "return hasSpecTypeSlot(getSpecRoot(), parseInt(arguments[0], 10) || 0);"
)

_SECOND_SPEC_ROW_VISIBLE_JS = (
    _SPEC_DOM_CORE_JS + "return secondSpecRowVisible(getSpecRoot());"
)

_FIRST_SPEC_CONFIGURED_JS = (
    _SPEC_DOM_CORE_JS + "return isFirstSpecConfigured(getSpecRoot());"
)

_CLICK_ADD_SPEC_TYPE_JS = (
    _SPEC_DOM_CORE_JS
    + """
const spec = getSpecRoot();
if (!spec) return { clicked: false, reason: 'no_spec' };
spec.scrollIntoView({ block: 'center', behavior: 'instant' });
const before = getAddBtnMeta(spec);
const buttons = [...spec.querySelectorAll('button')].filter((btn) => {
    const compact = (btn.innerText || btn.textContent || '').replace(/\\s+/g, '');
    if (!compact.includes('添加规格类型')) return false;
    if (compact.includes('AI添加') || compact.includes('AI添加规格')) return false;
    return isVisible(btn);
});
if (!buttons.length) return { clicked: false, reason: 'no_button', before: before.text };
const btn = buttons[0];
btn.scrollIntoView({ block: 'center', behavior: 'instant' });
try { btn.click(); } catch (e) {}
const after = getAddBtnMeta(spec);
const secondRow = secondSpecRowVisible(spec);
const increased = after.current > before.current;
const secondRowAdded = before.current === 1 && secondRow && !increased;
return {
    clicked: true,
    text: after.text || (btn.innerText || btn.textContent || '').trim(),
    before: before.text,
    after: after.text,
    beforeCount: before.current,
    afterCount: after.current,
    increased: increased,
    secondRowVisible: secondRow,
    secondRowAdded: secondRowAdded,
    success: increased || secondRowAdded || (before.current === 0 && secondRow),
    dropdownCount: findSpecTypeDropdownTriggers(spec).length,
};
"""
)

_CLICK_SPEC_BLOCK_DROPDOWN_JS = (
    _SPEC_DOM_CORE_JS
    + """
return openSpecTypeDropdownByIndex(parseInt(arguments[0], 10) || 0);
"""
)

_OPEN_SPEC_TYPE_DROPDOWN_JS = _CLICK_SPEC_BLOCK_DROPDOWN_JS

_LIST_SPEC_TYPE_OPTIONS_JS = """
function norm(t) { return (t || '').replace(/\\s+/g, ' ').trim(); }
function isVisibleEl(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function isRealSpecOption(raw) {
    const t = norm(raw).replace(/常用/g, '').replace(/\\s+/g, '');
    if (!t || t.length > 24) return false;
    if (t.includes('关键词搜索') || t.includes('无结果') || t.includes('功能/订单')) return false;
    const keys = ['颜色', '款式', '尺寸', '型号', '套餐', '规格', '器型', '材质', '容量', '色号', '口味'];
    return keys.some((k) => t === k || t.startsWith(k));
}
const options = [];
function addOption(raw) {
    const short = norm(raw).split(/\\s+/)[0];
    if (!short || !isRealSpecOption(raw)) return;
    if (!options.includes(short)) options.push(short);
}
for (const portal of document.querySelectorAll('[data-testid="beast-core-portal-main"]')) {
    if (!isVisibleEl(portal)) continue;
    for (const el of portal.querySelectorAll(
        '[data-testid="beast-core-select-option"], li[role="option"], [role="option"]'
    )) {
        if (!isVisibleEl(el)) continue;
        addOption(el.innerText || el.textContent || '');
    }
}
for (const panel of document.querySelectorAll(
    '[class*="ST_dropdownPanel"], [class*="dropdownPanel"], ul[role="listbox"]'
)) {
    if (!isVisibleEl(panel)) continue;
    for (const el of panel.querySelectorAll('li[role="option"], [role="option"], [class*="option"]')) {
        if (!isVisibleEl(el)) continue;
        addOption(el.innerText || el.textContent || '');
    }
}
for (const panel of document.querySelectorAll(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden), [class*="dropdown"]:not([class*="hidden"]), [class*="Dropdown"]:not([class*="hidden"]), [class*="popup"]:not([class*="hidden"])'
)) {
    const r = panel.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    for (const el of panel.querySelectorAll('[class*="option"], [class*="Option"], li, div, span')) {
        const raw = norm(el.innerText || el.textContent || '');
        if (!raw || !isRealSpecOption(raw)) continue;
        const er = el.getBoundingClientRect();
        if (er.width < 2 || er.height < 2) continue;
        addOption(raw);
    }
}
return options.slice(0, 30);
"""

_PICK_SPEC_TYPE_OPTION_JS = """
function norm(t) {
    return (t || '').replace(/\\s+/g, '').replace(/常用/g, '');
}
function isVisibleEl(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function isRealSpecOption(raw) {
    const t = norm(raw);
    if (!t || t.length > 24) return false;
    if (t.includes('关键词搜索') || t.includes('无结果') || t.includes('功能/订单')) return false;
    const keys = ['颜色', '款式', '尺寸', '型号', '套餐', '规格', '器型', '材质', '容量', '色号', '口味'];
    return keys.some((k) => t === k || t.startsWith(k));
}
function tryPickOption(el, typeName, target) {
    const raw = (el.innerText || el.textContent || '').trim();
    if (!raw || !isRealSpecOption(raw)) return '';
    const t = norm(raw);
    if (t !== target && !t.startsWith(target) && !raw.startsWith(typeName)) return '';
    const er = el.getBoundingClientRect();
    if (er.width < 2 || er.height < 2) return '';
    el.click();
    return raw.split(/\\s+/)[0];
}
const typeName = String(arguments[0] || '').trim();
const target = norm(typeName);
if (!target) return '';

for (const portal of document.querySelectorAll('[data-testid="beast-core-portal-main"]')) {
    if (!isVisibleEl(portal)) continue;
    for (const el of portal.querySelectorAll(
        '[data-testid="beast-core-select-option"], li[role="option"], [role="option"]'
    )) {
        if (!isVisibleEl(el)) continue;
        const picked = tryPickOption(el, typeName, target);
        if (picked) return picked;
    }
}

for (const panel of document.querySelectorAll(
    '[class*="ST_dropdownPanel"], [class*="dropdownPanel"], ul[role="listbox"]'
)) {
    if (!isVisibleEl(panel)) continue;
    for (const el of panel.querySelectorAll('li[role="option"], [role="option"], [class*="option"]')) {
        if (!isVisibleEl(el)) continue;
        const picked = tryPickOption(el, typeName, target);
        if (picked) return picked;
    }
}

const panels = [
    ...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)'),
    ...document.querySelectorAll('[class*="dropdown"]:not([class*="hidden"])'),
    ...document.querySelectorAll('[class*="Dropdown"]:not([class*="hidden"])'),
    ...document.querySelectorAll('[class*="popup"]:not([class*="hidden"])'),
];
for (const panel of panels) {
    const r = panel.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    for (const el of panel.querySelectorAll(
        '[class*="option"], [class*="Option"], li, div, span'
    )) {
        const picked = tryPickOption(el, typeName, target);
        if (picked) return picked;
    }
}
return '';
"""

_COUNT_BLOCK_VALUE_INPUTS_JS = (
    _SPEC_DOM_CORE_JS
    + "return findSpecValueInputs(getSpecRoot(), parseInt(arguments[0], 10) || 0).length;"
)

_FILL_SPEC_VALUE_AT_BLOCK_JS = (
    _SPEC_DOM_CORE_JS
    + """
const blockIndex = parseInt(arguments[0], 10) || 0;
const value = String(arguments[1] || '').trim();
if (!value) return { ok: false, reason: 'empty_value' };
const spec = getSpecRoot();
const inputs = findSpecValueInputs(spec, blockIndex);
const inp = inputs.length ? inputs[inputs.length - 1] : null;
if (!inp) {
    return {
        ok: false,
        reason: 'no_input',
        blockIndex,
        inputCount: inputs.length,
        inferredCount: inferSpecTypeCount(spec),
    };
}
try { inp.focus(); } catch (e) {}
const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
if (setter) setter.call(inp, value);
else inp.value = value;
inp.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
inp.dispatchEvent(new Event('change', { bubbles: true }));
inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
inp.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
try { inp.blur(); } catch (e) {}
return { ok: (inp.value || '').trim() === value, value: (inp.value || '').trim(), inputCount: inputs.length };
"""
)


def _log(account_id: str, message: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    print(f"{prefix} [新店铺规格] {message}", flush=True)


def _log_json(account_id: str, tag: str, payload: object) -> None:
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        text = str(payload)
    if len(text) > 1200:
        text = text[:1200] + "..."
    _log(account_id, f"{tag}: {text}")


def parse_new_shop_detect_result(raw: object) -> tuple[bool, str]:
    """解析 ``_DETECT_NEW_SHOP_SPEC_UI_JS`` 返回值。"""
    if isinstance(raw, dict):
        return bool(raw.get("isNew")), str(raw.get("reason") or "")
    if raw is None:
        return False, "none"
    return bool(raw), "bool"


def _snapshot_spec_dom(page, account_id: str, step: str) -> dict:
    try:
        snap = page.run_js(_SNAPSHOT_SPEC_DOM_JS)
        if isinstance(snap, dict):
            _log_json(account_id, f"DOM快照[{step}]", snap)
            return snap
    except Exception as exc:
        _log(account_id, f"DOM快照[{step}] 失败：{exc}")
    return {}


def _scroll_spec_into_view(page, account_id: str) -> None:
    try:
        page.run_js(_SCROLL_SPEC_INTO_VIEW_JS)
        _log(account_id, "已滚动规格区到视口")
    except Exception as exc:
        _log(account_id, f"滚动规格区失败：{exc}")
    time.sleep(0.3)


def _count_spec_blocks(page) -> int:
    try:
        count = int(page.run_js(_GET_SPEC_TYPE_COUNT_JS) or 0)
        if count > 0:
            return count
    except Exception:
        pass
    return len(_new_spec_items(page))


def _read_add_btn_snapshot(page) -> dict:
    try:
        snap = page.run_js(_SNAPSHOT_SPEC_DOM_JS)
        if isinstance(snap, dict):
            return snap
    except Exception:
        pass
    return {}


def _read_add_btn_current(page) -> int:
    snap = _read_add_btn_snapshot(page)
    text = str(snap.get("addBtnText") or "")
    cur = snap.get("addBtnCurrent")
    if "添加规格类型" in text and isinstance(cur, int):
        return int(cur)
    return 0


def _read_add_spec_count(page) -> int:
    snap = _read_add_btn_snapshot(page)
    text = str(snap.get("addBtnText") or "")
    cur = snap.get("addBtnCurrent")
    by_dropdown = int(snap.get("dropdownCount") or 0)
    if snap.get("secondRowVisible"):
        return max(2, by_dropdown, int(cur) if isinstance(cur, int) else 0)
    if "添加规格类型" in text and isinstance(cur, int):
        return max(int(cur), by_dropdown)
    slots = snap.get("specTypeSlotCount") or snap.get("inferredCount") or 0
    try:
        return min(int(slots), 2)
    except (TypeError, ValueError):
        return 0


def _has_spec_type_slot(page, index: int) -> bool:
    try:
        return bool(page.run_js(_HAS_SPEC_TYPE_SLOT_JS, index))
    except Exception:
        return False


def _second_spec_row_visible(page) -> bool:
    try:
        if page.run_js(_SECOND_SPEC_ROW_VISIBLE_JS):
            return True
    except Exception:
        pass
    for text in ("规格类型2", "请先选择规格类型2", "请选择或输入规格类型"):
        try:
            if page.ele(f"text:{text}", timeout=0.3):
                return True
        except Exception:
            pass
    return False


def _wait_first_spec_configured(
    page,
    account_id: str,
    *,
    max_wait: int = 15,
) -> bool:
    """第一组必须选完类型并填好规格值后，才允许添加第二组。"""
    for attempt in range(max_wait):
        try:
            if page.run_js(_FIRST_SPEC_CONFIGURED_JS):
                _log(account_id, "第一组规格已配置完成，可添加第二组")
                return True
        except Exception as exc:
            if attempt == 0:
                _log(account_id, f"检测第一组配置状态异常：{exc}")
        if attempt == 0 or (attempt + 1) % 4 == 0:
            _log(account_id, f"等待第一组规格配置完成 ({attempt + 1}/{max_wait})")
        time.sleep(0.4)
    _snapshot_spec_dom(page, account_id, "first_spec_not_configured")
    return False


def _new_spec_items(page):
    container = page.ele("#spec", timeout=3)
    if not container:
        return []
    items = container.eles("css:.goods-spec-item")
    if items:
        return items
    items = container.eles("css:.goods-spec-row-box")
    if items:
        return items
    wrapper = container.ele("css:.goods-spec-wrapper", timeout=0.5) or container.ele(
        "css:.goods-sku-box.goods-spec-wrapper", timeout=0.5
    )
    if not wrapper:
        return []
    candidates = []
    for child in wrapper.eles("css:div"):
        if child.ele("css:input@placeholder:请输入规格名称", timeout=0.2):
            candidates.append(child)
            continue
        if child.ele("css:.ant-select-selector", timeout=0.2):
            candidates.append(child)
    return candidates


def is_new_shop_spec_ui(page, account_id: str = "") -> bool:
    """
    新店铺规格区：无旧版 ``.goods-spec-row-box``，有「添加规格类型」按钮。
    旧店铺：进入规格页即出现 ``.goods-spec-row-box``，走原 ``add_style_and_model_specs``。
    """
    detect_raw: object = None
    try:
        detect_raw = page.run_js(_DETECT_NEW_SHOP_SPEC_UI_JS)
        is_new, reason = parse_new_shop_detect_result(detect_raw)
        if account_id:
            _log_json(account_id, "UI检测", detect_raw)
            _log(account_id, f"UI检测结果：{'新店铺' if is_new else '旧店铺'}（{reason}）")
        return is_new
    except Exception as exc:
        if account_id:
            _log(account_id, f"UI检测 JS 异常：{exc}，回退 Python 检测")

    container = page.ele("#spec", timeout=2)
    if not container:
        if account_id:
            _log(account_id, "UI检测回退：未找到 #spec")
        return False
    if container.eles("css:.goods-spec-row-box"):
        if account_id:
            _log(account_id, "UI检测回退：发现 .goods-spec-row-box → 旧店铺")
        return False
    add_btn = page.ele("text:添加规格类型", timeout=1)
    if not add_btn:
        if account_id:
            _log(account_id, "UI检测回退：无添加规格类型按钮 → 旧店铺")
        return False
    if container.ele("css:.goods-spec-wrapper", timeout=0.5):
        if account_id:
            _log(account_id, "UI检测回退：有 wrapper + 添加按钮 → 新店铺")
        return True
    is_new = len(container.eles("css:.goods-spec-item")) == 0
    if account_id:
        _log(account_id, f"UI检测回退：无 spec-item → {'新店铺' if is_new else '旧店铺'}")
    return is_new


def _click_add_spec_type(page, account_id: str) -> bool:
    _click_blank_area(page)
    time.sleep(0.35)
    _scroll_spec_into_view(page, account_id)
    before = _read_add_btn_current(page)
    clicked = False
    meta: object = None
    try:
        meta = page.run_js(_CLICK_ADD_SPEC_TYPE_JS)
        if isinstance(meta, dict):
            clicked = bool(meta.get("clicked"))
            _log_json(account_id, "点击添加规格类型", meta)
        else:
            clicked = bool(meta)
    except Exception as exc:
        _log(account_id, f"点击添加规格类型 JS 异常：{exc}")

    if not clicked:
        btn = page.ele("text:添加规格类型", timeout=2)
        if btn:
            try:
                page.run_js(
                    "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();",
                    btn,
                )
                clicked = True
                _log(account_id, "点击添加规格类型（元素回退）")
            except Exception as exc:
                _log(account_id, f"点击添加规格类型回退失败：{exc}")

    if not clicked:
        _log(account_id, "未找到可点击的「添加规格类型」按钮")
        return False

    for attempt in range(10):
        after = _read_add_btn_current(page)
        if after > before:
            _log(account_id, f"添加规格类型成功：按钮 {before}/2 → {after}/2")
            return True
        if isinstance(meta, dict):
            if meta.get("success") or meta.get("secondRowAdded"):
                _log(
                    account_id,
                    "添加规格类型成功（第二组规格行已出现，添加按钮已隐藏）",
                )
                return True
            if meta.get("increased"):
                _log(
                    account_id,
                    f"添加规格类型成功（按钮 increased）：{meta.get('before')} → {meta.get('after')}",
                )
                return True
        if before >= 1 and _second_spec_row_visible(page):
            _log(account_id, "添加规格类型成功（检测到第二组规格行）")
            return True
        if attempt == 0 or (attempt + 1) % 3 == 0:
            _log(
                account_id,
                f"等待按钮计数增加 {before}/2 → ? ({attempt + 1}/10)",
            )
        time.sleep(0.4)

    after = _read_add_btn_current(page)
    if before >= 1 and _second_spec_row_visible(page):
        _log(account_id, "添加规格类型成功（等待后检测到第二组规格行）")
        return True
    _log(account_id, f"按钮计数未增加：{before}/2 → {after}/2")
    _snapshot_spec_dom(page, account_id, "add_spec_no_increase")
    return after > before


def _wait_spec_blocks(page, count: int, account_id: str, *, max_wait: int = 12) -> bool:
    """等待规格组就绪；按钮 (N/2)、规格类型N 或类型下拉数达到目标即成功。"""
    for attempt in range(max_wait):
        block_count = _count_spec_blocks(page)
        add_count = _read_add_spec_count(page)
        if block_count >= count or add_count >= count or _has_spec_type_slot(page, count - 1):
            _log(
                account_id,
                f"规格组已就绪 slots={block_count} addBtn={add_count} 目标={count}",
            )
            return True
        if attempt == 0 or (attempt + 1) % 3 == 0:
            _log(
                account_id,
                f"等待规格组 inferred={block_count} addBtn={add_count} "
                f"目标={count} ({attempt + 1}/{max_wait})",
            )
            if attempt == 0:
                _snapshot_spec_dom(page, account_id, f"wait_blocks_{count}")
        time.sleep(0.4)
    block_count = _count_spec_blocks(page)
    add_count = _read_add_spec_count(page)
    _log(
        account_id,
        f"等待规格组结束 inferred={block_count} addBtn={add_count} 目标={count}",
    )
    _snapshot_spec_dom(page, account_id, f"wait_blocks_done_{count}")
    return (
        block_count >= count
        or _read_add_btn_current(page) >= count
        or _has_spec_type_slot(page, count - 1)
    )


def _list_spec_type_options(page) -> list[str]:
    try:
        raw_opts = page.run_js(_LIST_SPEC_TYPE_OPTIONS_JS)
        if isinstance(raw_opts, list):
            return [str(x) for x in raw_opts if x]
    except Exception:
        pass
    return []


def _wait_spec_type_options(
    page,
    account_id: str,
    block_index: int,
    *,
    max_wait: int = 20,
) -> list[str]:
    """打开下拉后轮询选项，避免面板尚未渲染就读取为空。"""
    for attempt in range(max_wait):
        options = _list_spec_type_options(page)
        if options:
            return options
        if attempt == 0 or (attempt + 1) % 5 == 0:
            _log(
                account_id,
                f"等待第 {block_index + 1} 组规格类型选项 ({attempt + 1}/{max_wait})",
            )
        time.sleep(0.15)
    return []


def _pick_spec_type_playwright(page, type_name: str) -> str:
    for sel in (
        f'[data-testid="beast-core-portal-main"] [data-testid="beast-core-select-option"]:text-is("{type_name}")',
        f'[data-testid="beast-core-portal-main"] li[role="option"]:text-is("{type_name}")',
        f'.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option:has-text("{type_name}")',
    ):
        try:
            opt = page.ele(f"css:{sel}", timeout=0.4)
            if opt:
                page.run_js("arguments[0].click();", opt)
                return type_name
        except Exception:
            pass
    try:
        portal = page.ele('[data-testid="beast-core-portal-main"]', timeout=0.5)
        if portal:
            for candidate in (type_name, f"{type_name}常用"):
                opt = portal.ele(f"text:{candidate}", timeout=0.3)
                if opt:
                    page.run_js("arguments[0].click();", opt)
                    return type_name
    except Exception:
        pass
    return ""


def _click_beast_spec_select(page, block_index: int) -> bool:
    container = page.ele("#spec", timeout=1)
    if not container:
        return False
    selects = container.eles('css:[data-testid="beast-core-select"]')
    if block_index >= len(selects):
        return False
    sel = selects[block_index]
    header = sel.ele('[data-testid="beast-core-select-header"]', timeout=0.4)
    pointer = (
        header
        or sel.ele('css:[class*="pointerCell"]', timeout=0.4)
        or sel.ele('css:[class*="suffixCell"]', timeout=0.4)
    )
    if not pointer:
        return False
    try:
        page.run_js(
            """
            const el = arguments[0];
            el.scrollIntoView({block:'center'});
            el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
            el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true, view:window}));
            el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
            """,
            pointer,
        )
        return True
    except Exception:
        return False


def _open_spec_type_dropdown(page, block_index: int, account_id: str) -> bool:
    try:
        meta = page.run_js(_OPEN_SPEC_TYPE_DROPDOWN_JS, block_index)
        if isinstance(meta, dict):
            _log_json(account_id, f"打开下拉[{block_index}]", meta)
            return bool(meta.get("ok"))
    except Exception as exc:
        _log(account_id, f"打开下拉[{block_index}] JS 异常：{exc}")
    return _click_beast_spec_select(page, block_index)


def _select_spec_type_at_block(
    page,
    block_index: int,
    type_name: str,
    account_id: str,
) -> bool:
    _log(account_id, f"准备打开第 {block_index + 1} 组规格类型下拉，目标={type_name!r}")

    for attempt in range(3):
        if attempt > 0:
            _click_blank_area(page)
            time.sleep(0.25)

        opened = _open_spec_type_dropdown(page, block_index, account_id)
        if not opened:
            type_label = f"规格类型{block_index + 1}"
            trigger = page.ele(f"text:{type_label}", timeout=0.8)
            if trigger:
                try:
                    page.run_js(
                        "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();",
                        trigger,
                    )
                    opened = True
                    _log(account_id, f"打开下拉（文本回退 {type_label}）")
                except Exception as exc:
                    _log(account_id, f"文本回退 {type_label} 失败：{exc}")

        if not opened and not _click_beast_spec_select(page, block_index):
            items = _new_spec_items(page)
            if block_index < len(items):
                return _select_spec_type(items[block_index], type_name, page, account_id)
            _log(account_id, f"第 {block_index + 1} 组无法打开下拉（尝试 {attempt + 1}/3）")
            time.sleep(0.4)
            continue

        options = _wait_spec_type_options(page, account_id, block_index)
        if options:
            _log(account_id, f"可见规格类型选项：{', '.join(options[:12])}")
        elif attempt < 2:
            _log(
                account_id,
                f"第 {block_index + 1} 组下拉选项为空，重试打开（{attempt + 1}/3）",
            )
            continue

        picked = ""
        try:
            picked = str(page.run_js(_PICK_SPEC_TYPE_OPTION_JS, type_name) or "").strip()
        except Exception as exc:
            _log(account_id, f"选择规格类型 {type_name} JS 异常：{exc}")

        if not picked:
            picked = _pick_spec_type_playwright(page, type_name)

        if picked:
            _log(account_id, f"第 {block_index + 1} 组已选规格类型：{picked}")
            time.sleep(0.5)
            return True

        items = _new_spec_items(page)
        if block_index < len(items) and _select_spec_type(
            items[block_index], type_name, page, account_id
        ):
            return True

        _log(
            account_id,
            f"第 {block_index + 1} 组未能选择规格类型 {type_name!r}（选项={options[:8]}）",
        )
        if attempt < 2:
            continue
        return False

    return False


def _select_spec_type_at_block_with_fallback(
    page,
    block_index: int,
    type_names: list[str],
    account_id: str,
) -> str:
    for type_name in type_names:
        if _select_spec_type_at_block(page, block_index, type_name, account_id):
            return type_name
    return ""


def _ensure_spec_block(page, account_id: str, index: int) -> bool:
    """确保第 index 个规格组存在（0-based）。"""
    needed = index + 1
    snap = _read_add_btn_snapshot(page)
    add_text = str(snap.get("addBtnText") or "")
    add_current = _read_add_btn_current(page)

    if _has_spec_type_slot(page, index):
        _log(
            account_id,
            f"规格组 #{needed} 已就绪（slots={_read_add_spec_count(page)} addBtn={add_text or add_current}）",
        )
        return True

    if index >= 1 and _second_spec_row_visible(page):
        _log(account_id, f"规格组 #{needed} 已存在（第二组规格行可见，无需再点添加）")
        return True

    if add_text and "添加规格类型" in add_text and add_current < needed:
        _log(
            account_id,
            f"添加按钮显示 {add_text}，需点击添加第 {needed} 组规格",
        )

    for attempt in range(3):
        if _has_spec_type_slot(page, index) or (index >= 1 and _second_spec_row_visible(page)):
            _log(account_id, f"规格组 #{needed} 已出现（尝试 {attempt + 1}/3 前检测）")
            return True
        _log(
            account_id,
            f"点击添加规格组 #{needed}（addBtn={add_text or add_current}）尝试 {attempt + 1}/3",
        )
        if _click_add_spec_type(page, account_id):
            if _wait_spec_blocks(page, needed, account_id):
                return True
            if _has_spec_type_slot(page, index):
                _log(account_id, f"规格组 #{needed} 已出现")
                return True
            add_current = _read_add_btn_current(page)
            if add_current >= needed:
                _log(account_id, f"规格组 #{needed} 已就绪（addBtn={add_current}/2）")
                return True
        time.sleep(0.6)

    if _has_spec_type_slot(page, index):
        return True
    if index >= 1 and _second_spec_row_visible(page):
        return True
    add_current = _read_add_btn_current(page)
    if add_current >= needed:
        return True
    _log(account_id, f"添加后仍未达到规格组 #{needed}（addBtn={add_current}/2）")
    _snapshot_spec_dom(page, account_id, f"ensure_block_{index}_fail")
    return False


def _wait_block_value_inputs(
    page,
    block_index: int,
    count: int,
    account_id: str,
    label: str,
    *,
    max_wait: int = 20,
) -> bool:
    for attempt in range(max_wait):
        try:
            cur = int(page.run_js(_COUNT_BLOCK_VALUE_INPUTS_JS, block_index) or 0)
        except Exception:
            cur = 0
        if cur >= count:
            return True
        if attempt == 0 or (attempt + 1) % 5 == 0:
            _log(account_id, f"等待{label}输入框 ({cur}/{count}) ({attempt + 1}/{max_wait})")
        time.sleep(0.35)
    return False


def _add_values_to_spec_block(
    page,
    block_index: int,
    account_id: str,
    label: str,
    names: list[str],
) -> None:
    if not names:
        _log(account_id, f"{label} 规格值为空，跳过")
        return

    for i, name in enumerate(names):
        if i > 0:
            _wait_block_value_inputs(page, block_index, i + 1, account_id, label)
            time.sleep(0.2)

        filled = False
        try:
            result = page.run_js(_FILL_SPEC_VALUE_AT_BLOCK_JS, block_index, name)
            if isinstance(result, dict) and result.get("ok"):
                filled = True
        except Exception as exc:
            _log(account_id, f"JS 填值失败：{exc}")

        if not filled:
            items = _new_spec_items(page)
            if block_index < len(items):
                item = items[block_index]
                inputs = _inputs_in_box(item)
                if inputs:
                    current = inputs[-1]
                    try:
                        current.click()
                    except Exception:
                        page.run_js("arguments[0].click();", current)
                    time.sleep(0.15)
                    if not _react_fill_spec_input(page, current, name):
                        current.input(name, clear=True)
                        time.sleep(0.2)
                        current.input("\n")
                    filled = True

        if not filled:
            _log(account_id, f"未能录入 {label} ({i + 1}/{len(names)})：{name}")
            _snapshot_spec_dom(page, account_id, f"fill_fail_{label}_{i}")
            return

        _click_blank_area(page)
        _log(account_id, f"已录入{label} ({i + 1}/{len(names)})：{name}")
        time.sleep(0.35)


def add_style_and_model_specs_new_shop(
    page,
    account_id: str,
    style_names: list[str],
    model_names: list[str],
) -> bool:
    """
    新店铺规格录入：
    1. 点击「添加规格类型」
    2. 下拉选择第一维（颜色/款式）并填 style_names
    3. 再点「添加规格类型」
    4. 下拉选择第二维（尺寸/型号）并填 model_names
    """
    started = time.perf_counter()
    _log(
        account_id,
        f"开始新店铺规格录入 style={style_names} size={model_names}",
    )
    _scroll_spec_into_view(page, account_id)
    _snapshot_spec_dom(page, account_id, "start")

    container = page.ele("#spec", timeout=3)
    if not container:
        _log(account_id, "未找到 #spec 规格区域")
        return False

    if not _ensure_spec_block(page, account_id, 0):
        _log(account_id, "未能创建第一个规格组")
        return False

    first_type = _select_spec_type_at_block_with_fallback(
        page, 0, ["颜色", "款式"], account_id
    )
    first_label = first_type or "颜色"
    if not first_type:
        _log(account_id, "第一维规格类型选择失败")
        return False
    _add_values_to_spec_block(page, 0, account_id, first_label, style_names)
    _click_blank_area(page)
    time.sleep(0.5)
    _snapshot_spec_dom(page, account_id, "after_first_dim")

    if not _wait_first_spec_configured(page, account_id):
        _log(account_id, "第一组规格未配置完成，暂不添加第二组")
        return False

    _log(account_id, f"开始添加第二维规格（尺寸），当前 addBtn={_read_add_spec_count(page)}")
    if not _ensure_spec_block(page, account_id, 1):
        _log(account_id, "未能创建第二个规格组（尺寸）")
        return False

    second_type = _select_spec_type_at_block_with_fallback(
        page, 1, ["尺寸", "型号"], account_id
    )
    second_label = second_type or "尺寸"
    if not second_type:
        _log(account_id, "第二维规格类型选择失败，仍尝试填值")
    _add_values_to_spec_block(page, 1, account_id, second_label, model_names)
    _click_blank_area(page)
    _snapshot_spec_dom(page, account_id, "after_second_dim")

    _log(account_id, "等待规格矩阵生成…")
    _wait_spec_matrix_rows(page, account_id, style_names, model_names)
    _activate_spec_price_table(page, style_names, model_names, account_id=account_id)
    _log(
        account_id,
        f"款式、尺寸已全部录入，准备填写下方价格表（耗时 {time.perf_counter() - started:.1f}s）",
    )
    page.run_js(
        "document.querySelector('.sku-table,.sku-list')?.scrollIntoView({block:'center'});"
    )
    time.sleep(0.8)
    return True


def add_style_and_model_specs_auto(
    page,
    account_id: str,
    style_names: list[str],
    model_names: list[str],
) -> bool:
    """按页面形态自动选择旧店铺或新店铺规格录入流程。"""
    _log(
        account_id,
        f"规格自动分流 style_names={style_names} model_names={model_names}",
    )
    if is_new_shop_spec_ui(page, account_id=account_id):
        _log(account_id, "→ 走新店铺「添加规格类型」流程")
        result = add_style_and_model_specs_new_shop(
            page, account_id, style_names, model_names
        )
        _log(account_id, f"新店铺规格录入结果：{'成功' if result else '失败'}")
        return result

    _log(account_id, "→ 走旧店铺直接填规格流程")
    result = add_style_and_model_specs(page, account_id, style_names, model_names)
    _log(account_id, f"旧店铺规格录入结果：{'成功' if result else '失败'}")
    return result

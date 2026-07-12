"""上架提交前：满件折扣、服务与承诺（运费模板）页面设置。"""

from __future__ import annotations

import json
import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.listing.listing_shipping_template_priority import (
    DEFAULT_SHIPPING_TEMPLATE,
    flatten_shipping_template_candidates,
    iter_shipping_template_selection_attempts,
    resolve_matched_template_name,
    shipping_state_matches_acceptable,
)
from pdd_agent.skills.listing.multi_spec_page import _safe_exc

DEFAULT_BULK_DISCOUNT = "9.9"

_NATIVE_INPUT_SETTER_JS = """
const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
function setInputValue(input, value) {
  if (!input) return false;
  try { input.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
  try { input.focus({ preventScroll: true }); } catch (e) { try { input.focus(); } catch (e2) {} }
  const text = String(value);
  setter.call(input, text);
  input.dispatchEvent(new InputEvent('input', {
    bubbles: true, data: text, inputType: 'insertText'
  }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  try { input.blur(); } catch (e) {}
  return String(input.value || '').trim() === text;
}
"""

_SCROLL_BULK_DISCOUNT_JS = """
for (const marker of ['满2件折扣', '满件折扣', '满2件']) {
  for (const el of document.querySelectorAll('label,div,span,p,td,th')) {
    const t = (el.textContent || '').trim();
    if (!t.includes(marker) || t.length > 120) continue;
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    return { ok: true, marker };
  }
}
return { ok: false };
"""

_FIND_DISCOUNT_INPUT_JS = """
function isDiscountInput(input) {
  if (!input || input.disabled || input.readOnly) return false;
  const type = (input.type || 'text').toLowerCase();
  if (['hidden', 'file', 'checkbox', 'radio', 'button', 'submit'].includes(type)) return false;
  const ph = input.getAttribute('placeholder') || '';
  const v = String(input.value || '').trim();
  return ph.includes('5.0') || ph.includes('9.9') || v === '9.5' || v === '9.9' || /^\\d(\\.\\d)?$/.test(v);
}
function findDiscountInput() {
  const markers = ['满2件折扣', '满件折扣', '满2件'];
  for (const marker of markers) {
    for (const el of document.querySelectorAll('label,div,span,p,td,th,section')) {
      const t = (el.textContent || '').trim();
      if (!t.includes(marker) || t.length > 220) continue;
      let node = el;
      for (let depth = 0; depth < 14 && node; depth++) {
        const inputs = Array.from(node.querySelectorAll(
          'input[data-testid="beast-core-input-htmlInput"],'
          + 'input[data-testid="beast-core-input-nativeInput"], input'
        )).filter(isDiscountInput);
        if (inputs.length) return inputs[0];
        node = node.parentElement;
      }
    }
  }
  for (const input of document.querySelectorAll(
    'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"], input'
  )) {
    if (isDiscountInput(input)) return input;
  }
  return null;
}
"""

_SET_BULK_DISCOUNT_JS = (
    _NATIVE_INPUT_SETTER_JS
    + _FIND_DISCOUNT_INPUT_JS
    + """
function setBulkDiscount(value) {
  const input = findDiscountInput();
  if (!input) return { ok: false, reason: 'discount_input_not_found' };
  const before = String(input.value || '').trim();
  const applied = setInputValue(input, value);
  const after = String(input.value || '').trim();
  return {
    ok: applied || after === String(value),
    before,
    after,
    verified: after === String(value),
  };
}
return setBulkDiscount(arguments[0]);
"""
)

_READ_BULK_DISCOUNT_JS = (
    _FIND_DISCOUNT_INPUT_JS
    + """
const input = findDiscountInput();
return input ? String(input.value || '').trim() : '';
"""
)

_CLICK_SERVICE_TAB_JS = """
function clickServiceTab() {
  const tracked = document.querySelector(
    '[data-tracking-click-viewid*="service_promise"],'
    + '[data-tracking-click-viewid*="service_commitment"],'
    + '[data-tracking-click-viewid*="service_tab"]'
  );
  if (tracked) {
    tracked.click();
    return { ok: true, method: 'tracking' };
  }
  for (const el of document.querySelectorAll('div,span,a,li,button,[role="tab"]')) {
    const t = (el.textContent || '').replace(/\\s+/g, '');
    if (t === '服务与承诺' || t.endsWith('服务与承诺') || t.includes('3服务与承诺')) {
      (el.closest('[role="tab"]') || el.closest('button') || el).click();
      return { ok: true, method: 'tab_text' };
    }
  }
  return { ok: false, reason: 'service_tab_not_found' };
}
return clickServiceTab();
"""

_SHIPPING_COMMON_JS = """
function norm(text) {
  return String(text || '').replace(/\\s+/g, '');
}
function isVisible(el) {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) === 0) {
    return false;
  }
  const rect = el.getBoundingClientRect();
  return rect.width > 8 && rect.height > 8;
}
function findServiceSectionRoot() {
  for (const sel of ['.goods-service-v2', '.goods-service', '[class*="goods-service"]']) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  for (const el of document.querySelectorAll('div,section')) {
    const t = (el.textContent || '').trim();
    if (t.startsWith('3 服务与承诺') || t.includes('3 服务与承诺') || t.includes('3服务与承诺')) {
      return el;
    }
  }
  return null;
}
function findExpandButton() {
  const scope = findServiceSectionRoot() || document;
  const tracked = scope.querySelector('[data-tracking-click-id-v2="sl_expand_all_button"]');
  if (tracked) {
    const target = tracked.closest('.bottom-switch') || tracked;
    if (isVisible(target)) return target;
  }
  for (const el of scope.querySelectorAll('.bottom-switch, .text-v2, span, div, a, button')) {
    const t = norm(el.textContent);
    if (t !== '展开修改' && !t.endsWith('展开修改')) continue;
    const target = el.closest('.bottom-switch') || el;
    if (isVisible(target)) return target;
  }
  return null;
}
function isShippingTemplateHeader(header) {
  const t = norm(header.textContent);
  if (!t) return false;
  if (t.includes('品牌') || t.includes('搜索') || t.includes('请输入')) return false;
  if (t.includes('分类') || t.includes('类目') || t.includes('属性')) return false;
  return true;
}
function findOtherTemplateNodes(scope) {
  return Array.from(scope.querySelectorAll(
    'label,span,div,[data-testid="beast-core-radio"]'
  )).filter((node) => {
    const nt = norm(node.textContent);
    return nt === '其他模板' || nt.startsWith('其他模板');
  });
}
function findShippingFormBlock() {
  const serviceRoot = findServiceSectionRoot();
  if (!serviceRoot) return null;
  const candidates = [];
  for (const el of serviceRoot.querySelectorAll('div,tr,section,form,table')) {
    const t = norm(el.textContent);
    if (!t.includes('运费模板') || !t.includes('其他模板')) continue;
    if (t.length > 5000) continue;
    const others = findOtherTemplateNodes(el).filter(isVisible);
    if (!others.length) continue;
    candidates.push({ el, len: t.length });
  }
  candidates.sort((a, b) => a.len - b.len);
  return candidates.length ? candidates[0].el : null;
}
function isOtherTemplateChecked(block) {
  return findOtherTemplateNodes(block || findShippingFormBlock()).some((el) => {
    const radio = el.querySelector?.('input[type="radio"]')
      || el.closest('label')?.querySelector?.('input[type="radio"]')
      || el.closest('[data-testid="beast-core-radio"]')?.querySelector?.('input[type="radio"]');
    return radio ? radio.checked : false;
  });
}
function findShippingTemplateHeader(block) {
  const scopes = [];
  if (block) scopes.push(block);
  const serviceRoot = findServiceSectionRoot();
  if (serviceRoot && serviceRoot !== block) scopes.push(serviceRoot);
  for (const scope of scopes) {
    for (const otherNode of findOtherTemplateNodes(scope)) {
      let container = otherNode;
      for (let depth = 0; depth < 12 && container; depth++) {
        const headers = Array.from(container.querySelectorAll(
          '[data-testid="beast-core-select-header"], [data-testid*="select-header"], [role="combobox"]'
        )).filter((h) => isVisible(h) && isShippingTemplateHeader(h));
        if (headers.length) return headers[headers.length - 1];
        container = container.parentElement;
      }
    }
    if (isOtherTemplateChecked(scope)) {
      const headers = Array.from(scope.querySelectorAll(
        '[data-testid="beast-core-select-header"], [data-testid*="select-header"], [role="combobox"]'
      )).filter((h) => isVisible(h) && isShippingTemplateHeader(h));
      if (headers.length) return headers[headers.length - 1];
    }
  }
  return null;
}
function isShippingSectionReady() {
  const expandBtn = findExpandButton();
  const formBlock = findShippingFormBlock();
  return !!(formBlock && !expandBtn);
}
"""

_CLICK_EXPAND_SERVICE_EDIT_JS = (
    _SHIPPING_COMMON_JS
    + """
function clickTarget(target) {
  try { target.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
  target.click();
  target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
  target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
  target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
}
function clickExpandEdit() {
  try { window.scrollTo(0, document.documentElement.scrollHeight); } catch (e) {}
  const section = findServiceSectionRoot();
  if (section) {
    try { section.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
  }
  const target = findExpandButton();
  if (!target) {
    const ready = isShippingSectionReady();
    return {
      ok: ready,
      reason: 'expand_button_not_found',
      formReady: ready,
    };
  }
  clickTarget(target);
  const ready = isShippingSectionReady();
  const expandStillVisible = !!findExpandButton();
  const header = findShippingTemplateHeader(findShippingFormBlock());
  return {
    ok: ready,
    method: target.matches?.('[data-tracking-click-id-v2="sl_expand_all_button"]')
      ? 'tracking_sl_expand_all_button'
      : 'bottom_switch',
    formReady: ready,
    expandStillVisible,
    headerText: header ? norm(header.textContent) : '',
  };
}
return clickExpandEdit();
"""
)

_DETECT_SERVICE_SECTION_JS = (
    _SHIPPING_COMMON_JS
    + """
const expandBtn = findExpandButton();
const formBlock = findShippingFormBlock();
const header = findShippingTemplateHeader(formBlock);
const ready = isShippingSectionReady();
return {
  formReady: ready,
  expandButtonVisible: !!expandBtn,
  collapsedSummaryVisible: !!expandBtn || Array.from(
    (findServiceSectionRoot() || document).querySelectorAll('span,div,label')
  ).some((el) => {
    const t = norm(el.textContent);
    return t.startsWith('运费模板') && !t.includes('其他模板') && isVisible(el);
  }),
  headerText: header ? norm(header.textContent) : '',
  formBlockFound: !!formBlock,
  otherTemplateChecked: isOtherTemplateChecked(formBlock),
};
"""
)

_IS_SERVICE_EXPANDED_JS = (
    _SHIPPING_COMMON_JS
    + """
const expandBtn = findExpandButton();
const formBlock = findShippingFormBlock();
const header = findShippingTemplateHeader(formBlock);
const ready = isShippingSectionReady();
return {
  expanded: ready,
  formReady: ready,
  hasExpandButton: !!expandBtn,
  headerText: header ? norm(header.textContent) : '',
};
"""
)

_FIND_SHIPPING_BLOCK_JS = (
    _SHIPPING_COMMON_JS
    + """
const expandBtn = findExpandButton();
const formBlock = findShippingFormBlock();
const header = findShippingTemplateHeader(formBlock);
const ready = isShippingSectionReady();
return { visible: ready, formReady: ready, headerText: header ? norm(header.textContent) : '' };
"""
)

_READ_SHIPPING_TEMPLATE_JS = (
    _SHIPPING_COMMON_JS
    + """
const block = findShippingFormBlock();
if (!block) {
  return {
    found: false,
    current: '',
    otherChecked: false,
    formReady: false,
    expandButtonVisible: !!findExpandButton(),
  };
}
const header = findShippingTemplateHeader(block);
const current = header ? norm(header.textContent) : '';
const otherChecked = isOtherTemplateChecked(block);
return {
  found: true,
  current,
  otherChecked,
  formReady: isShippingSectionReady(),
  expandButtonVisible: !!findExpandButton(),
};
"""
)

_SELECT_SHIPPING_TEMPLATE_JS = (
    _SHIPPING_COMMON_JS
    + """
function clickOtherTemplateRadio(scope) {
  for (const el of findOtherTemplateNodes(scope)) {
    if (!isVisible(el)) continue;
    const clickEl = el.closest('label')
      || el.closest('[data-testid="beast-core-radio"]')
      || el;
    clickEl.click();
    const radio = clickEl.querySelector?.('input[type="radio"]')
      || el.querySelector?.('input[type="radio"]')
      || el.closest('[data-testid="beast-core-radio"]')?.querySelector?.('input[type="radio"]');
    if (radio) {
      radio.checked = true;
      radio.dispatchEvent(new Event('change', { bubbles: true }));
      radio.dispatchEvent(new Event('input', { bubbles: true }));
      radio.click();
    }
    return true;
  }
  return false;
}
function waitForShippingHeader(block, maxMs) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const header = findShippingTemplateHeader(block);
    if (header) return header;
  }
  return null;
}
function normalizeOptionText(text) {
  return String(text || '').replace(/\\s+/g, '');
}
function optionMatches(text, optionText) {
  const t = normalizeOptionText(text);
  const want = normalizeOptionText(optionText);
  if (!want || !t) return false;
  return t === want || t.includes(want);
}
function collectVisibleOptions(roots) {
  const seen = new Set();
  const out = [];
  for (const root of roots) {
    for (const opt of root.querySelectorAll(
      '[data-testid="beast-core-select-option"], [role="option"], li[data-value]'
    )) {
      if (!isVisible(opt)) continue;
      const t = (opt.textContent || '').trim();
      if (!t || seen.has(t)) continue;
      seen.add(t);
      out.push({ el: opt, text: t });
    }
  }
  return out;
}
function selectDropdownOption(scope, optionText, aliases) {
  const header = findShippingTemplateHeader(scope) || waitForShippingHeader(scope, 1200);
  if (!header) return { ok: false, step: 'header_not_found' };
  header.click();
  const wants = [optionText, ...(aliases || [])].filter(Boolean);
  let matched = null;
  let allTexts = [];
  const start = Date.now();
  while (Date.now() - start < 2500) {
    const roots = [
      ...document.querySelectorAll('[data-testid="beast-core-portal-main"]'),
    ];
    if (!roots.length) roots.push(document.body);
    const options = collectVisibleOptions(roots);
    allTexts = options.map((o) => o.text);
    for (const want of wants) {
      for (const opt of options) {
        if (optionMatches(opt.text, want)) {
          matched = opt;
          break;
        }
      }
      if (matched) break;
    }
    if (matched) break;
  }
  if (!matched) {
    return { ok: false, step: 'option_not_found', optionText, visibleOptions: allTexts.slice(0, 30) };
  }
  try { matched.el.scrollIntoView({ block: 'nearest', behavior: 'instant' }); } catch (e) {}
  const clickTargets = [matched.el, matched.el.querySelector('span,div')].filter(Boolean);
  for (const target of clickTargets) {
    target.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true }));
    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    target.click();
    target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
    target.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true }));
  }
  const verifyStart = Date.now();
  while (Date.now() - verifyStart < 1200) {
    const h = findShippingTemplateHeader(scope);
    const ht = h ? norm(h.textContent) : '';
    if (wants.some((want) => optionMatches(ht, want))) {
      return { ok: true, selected: ht };
    }
  }
  return { ok: false, step: 'click_not_applied', optionText, visibleOptions: allTexts.slice(0, 30) };
}
function selectShipping(templateName, aliases) {
  const block = findShippingFormBlock();
  if (!block) return { ok: false, step: 'shipping_form_not_ready' };
  if (findExpandButton()) return { ok: false, step: 'need_expand_first' };
  try { block.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
  if (!isOtherTemplateChecked(block)) {
    if (!clickOtherTemplateRadio(block)) {
      return { ok: false, step: 'other_template_radio' };
    }
  }
  const header = waitForShippingHeader(block, 1500);
  if (!header) return { ok: false, step: 'header_not_found_after_other_radio' };
  const drop = selectDropdownOption(block, templateName, aliases || []);
  if (!drop.ok) return { ok: false, step: 'dropdown', detail: drop, headerText: norm(header.textContent) };
  return { ok: true, template: templateName, dropdown: drop };
}
return selectShipping(arguments[0], arguments[1] || []);
"""
)

_SCROLL_SERVICE_SECTION_JS = """
function norm(text) {
  return String(text || '').replace(/\\s+/g, '');
}
try {
  window.scrollTo(0, document.documentElement.scrollHeight);
} catch (e) {}
for (const el of document.querySelectorAll('div,section')) {
  const t = (el.textContent || '').trim();
  if (t.startsWith('3 服务与承诺') || t.includes('3 服务与承诺')) {
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    return { ok: true, method: 'section_heading' };
  }
}
for (const el of document.querySelectorAll('span,div,a,button,.bottom-switch,.text-v2')) {
  if (norm(el.textContent) === '展开修改') {
    (el.closest('.bottom-switch') || el).scrollIntoView({ block: 'center', behavior: 'instant' });
    return { ok: true, method: 'expand_button' };
  }
}
for (const el of document.querySelectorAll('span,div,label')) {
  if (norm(el.textContent) === '运费模板' || norm(el.textContent).startsWith('运费模板')) {
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    return { ok: true, method: 'freight_label' };
  }
}
return { ok: false };
"""


def _is_invalid_shipping_header(text: str) -> bool:
    current = str(text or "").replace(" ", "")
    if not current:
        return False
    bad_markers = ("品牌", "搜索", "请输入", "分类", "类目", "属性")
    return any(marker in current for marker in bad_markers)


def _shipping_state_is_valid(state: dict[str, Any]) -> bool:
    if state.get("expandButtonVisible"):
        return False
    if not state.get("found"):
        return False
    current = str(state.get("current") or "")
    if current and _is_invalid_shipping_header(current):
        return False
    return True


def _normalize_js_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"value": text}
    return {"value": raw}


def _read_bulk_discount_value(page: DpPage) -> str:
    try:
        raw = page.run_js(_READ_BULK_DISCOUNT_JS)
        return str(raw or "").strip()
    except Exception:
        return ""


def _detect_service_section(page: DpPage) -> dict[str, Any]:
    try:
        return _normalize_js_result(page.run_js(_DETECT_SERVICE_SECTION_JS))
    except Exception:
        return {}


def _is_shipping_form_ready(page: DpPage) -> bool:
    state = _detect_service_section(page)
    if "found" not in state and state.get("formReady") is not None:
        return bool(state.get("formReady"))
    try:
        raw = page.run_js(_FIND_SHIPPING_BLOCK_JS)
        result = _normalize_js_result(raw)
        return bool(result.get("formReady") or result.get("visible"))
    except Exception:
        return False


def _is_shipping_template_visible(page: DpPage) -> bool:
    return _is_shipping_form_ready(page)


def _is_service_section_expanded(page: DpPage) -> bool:
    return _is_shipping_form_ready(page)


def _read_shipping_template_state(page: DpPage) -> dict[str, Any]:
    try:
        return _normalize_js_result(page.run_js(_READ_SHIPPING_TEMPLATE_JS))
    except Exception:
        return {"found": False, "current": "", "otherChecked": False}


def _fill_discount_via_playwright(page: DpPage, discount: str) -> dict[str, Any]:
    try:
        raw_page = page._page
        for marker in ("满2件折扣", "满件折扣", "满2件"):
            label = raw_page.get_by_text(marker, exact=False).first
            try:
                label.wait_for(state="attached", timeout=800)
            except Exception:
                continue
            container = label.locator(
                "xpath=ancestor::*[self::div or self::section or self::tr or self::td][position()<=8]"
            ).first
            inputs = container.locator(
                'input[data-testid="beast-core-input-htmlInput"],'
                'input[data-testid="beast-core-input-nativeInput"], input'
            )
            count = inputs.count()
            for idx in range(count):
                inp = inputs.nth(idx)
                try:
                    if not inp.is_visible():
                        continue
                except Exception:
                    continue
                value = ""
                try:
                    value = (inp.input_value(timeout=500) or "").strip()
                except Exception:
                    pass
                if value in {"9.5", "9.9"} or (value.replace(".", "", 1).isdigit() and len(value) <= 4):
                    before = value
                    inp.scroll_into_view_if_needed(timeout=2000)
                    inp.fill(str(discount))
                    inp.blur()
                    after = (inp.input_value(timeout=500) or "").strip()
                    if after == str(discount):
                        return {
                            "ok": True,
                            "method": "playwright_fill",
                            "marker": marker,
                            "before": before,
                            "after": after,
                        }
        return {"ok": False, "reason": "discount_input_not_found"}
    except Exception as exc:
        return {"ok": False, "reason": "exception", "error": _safe_exc(exc)}


def _set_bulk_discount(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    discount: str,
) -> dict[str, Any]:
    discount = str(discount or DEFAULT_BULK_DISCOUNT).strip() or DEFAULT_BULK_DISCOUNT
    try:
        page.run_js(_SCROLL_BULK_DISCOUNT_JS)
        time.sleep(0.25)
        raw = page.run_js(_SET_BULK_DISCOUNT_JS, discount)
        result = _normalize_js_result(raw)
        if not result.get("ok") or result.get("after") != discount:
            btn = page.ele("text:修改", timeout=1)
            if btn and "满" in str(page.html or ""):
                btn.click()
                time.sleep(0.4)
                raw = page.run_js(_SET_BULK_DISCOUNT_JS, discount)
                result = _normalize_js_result(raw)
        if result.get("after") != discount:
            pw_result = _fill_discount_via_playwright(page, discount)
            if pw_result.get("ok"):
                result = pw_result
        time.sleep(0.2)
        visible = _read_bulk_discount_value(page)
        if visible == discount:
            result["ok"] = True
            result["after"] = visible
            result["verified"] = True
        if result.get("ok"):
            print(
                f"[{account_id}] [{label}] 满件折扣已设为 {discount}"
                f"（原值 {result.get('before', visible or '-')}）",
                flush=True,
            )
            return result
        print(
            f"[{account_id}] [{label}] 未找到满件折扣输入框或写入未生效："
            f"{result.get('reason', 'verify_failed')}，当前值={visible or '<空>'}",
            flush=True,
        )
        return result
    except Exception as exc:
        print(f"[{account_id}] [{label}] 满件折扣设置异常：{_safe_exc(exc)}", flush=True)
        return {"ok": False, "reason": "exception", "error": _safe_exc(exc)}


def _click_service_tab(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    try:
        raw = page.run_js(_CLICK_SERVICE_TAB_JS)
        result = _normalize_js_result(raw)
        if result.get("ok"):
            time.sleep(0.6)
            return result
        tab = page.ele("text:服务与承诺", timeout=2)
        if tab:
            tab.click(by_js=True)
            time.sleep(0.6)
            return {"ok": True, "method": "ele"}
        try:
            page._page.get_by_text("服务与承诺", exact=False).first.click(timeout=2500)
            time.sleep(0.6)
            return {"ok": True, "method": "playwright"}
        except Exception:
            pass
        print(f"[{account_id}] [{label}] 未找到「服务与承诺」Tab", flush=True)
        return result
    except Exception as exc:
        print(f"[{account_id}] [{label}] 切换服务与承诺 Tab 异常：{_safe_exc(exc)}", flush=True)
        return {"ok": False, "reason": "exception", "error": _safe_exc(exc)}


def _click_expand_service_edit(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    """滚到页面底部并点击「展开修改」。"""
    before = _detect_service_section(page)
    page.run_js(_SCROLL_SERVICE_SECTION_JS)
    time.sleep(0.35)
    raw = page.run_js(_CLICK_EXPAND_SERVICE_EDIT_JS)
    result = _normalize_js_result(raw)
    time.sleep(0.9)
    after = _detect_service_section(page)
    expand_ok = bool(result.get("formReady") or _is_shipping_form_ready(page))
    if expand_ok:
        header_text = result.get("headerText") or after.get("headerText") or ""
        print(
            f"[{account_id}] [{label}] 已点击「展开修改」（{result.get('method', 'js')}），"
            f"运费表单已就绪"
            + (f"，下拉框={header_text}" if header_text else ""),
            flush=True,
        )
        return {**result, "ok": True, "before": before, "after": after}

    btn = page.ele("text:展开修改", timeout=1)
    if btn:
        try:
            page.run_js(
                """
                try { window.scrollTo(0, document.documentElement.scrollHeight); } catch (e) {}
                """
            )
            time.sleep(0.2)
            btn.click(by_js=True)
            time.sleep(0.9)
            if _is_shipping_form_ready(page):
                print(
                    f"[{account_id}] [{label}] 已点击「展开修改」（ele_js），运费表单已就绪",
                    flush=True,
                )
                return {"ok": True, "method": "ele_js", "before": before, "after": _detect_service_section(page)}
        except Exception:
            pass

    try:
        page._page.locator('[data-tracking-click-id-v2="sl_expand_all_button"]').click(
            timeout=2500,
            force=True,
        )
        time.sleep(0.9)
        if _is_shipping_form_ready(page):
            print(
                f"[{account_id}] [{label}] 已点击「展开修改」（playwright_tracking），运费表单已就绪",
                flush=True,
            )
            return {
                "ok": True,
                "method": "playwright_tracking",
                "before": before,
                "after": _detect_service_section(page),
            }
    except Exception:
        pass

    try:
        page._page.locator(".bottom-switch").filter(has_text="展开修改").last.click(timeout=2500, force=True)
        time.sleep(0.9)
        if _is_shipping_form_ready(page):
            print(
                f"[{account_id}] [{label}] 已点击「展开修改」（playwright_bottom_switch），运费表单已就绪",
                flush=True,
            )
            return {
                "ok": True,
                "method": "playwright_bottom_switch",
                "before": before,
                "after": _detect_service_section(page),
            }
    except Exception:
        pass

    reason = str(result.get("reason") or "expand_click_not_effective")
    print(
        f"[{account_id}] [{label}] 未能点击「展开修改」或展开后运费表单仍不可用："
        f"{reason}；展开按钮可见={before.get('expandButtonVisible')}→{after.get('expandButtonVisible')}，"
        f"表单就绪={before.get('formReady')}→{after.get('formReady')}",
        flush=True,
    )
    return {**(result or {}), "ok": False, "reason": reason, "before": before, "after": after}


def _ensure_service_section_ready(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    """在当前页滚到底部，展开「3 服务与承诺」，直到运费模板可选。"""
    try:
        page.run_js(_SCROLL_SERVICE_SECTION_JS)
        time.sleep(0.3)

        section_state = _detect_service_section(page)
        if section_state.get("formReady") and not section_state.get("expandButtonVisible"):
            header_text = section_state.get("headerText") or ""
            other_checked = section_state.get("otherTemplateChecked")
            print(
                f"[{account_id}] [{label}] 运费模板区域已就绪（无需展开）"
                f"，其他模板={'已选' if other_checked else '未选'}"
                + (f"，下拉框={header_text}" if header_text else ""),
                flush=True,
            )
            return {"ok": True, "method": "already_ready", "state": section_state}

        if section_state.get("expandButtonVisible") or section_state.get("collapsedSummaryVisible"):
            print(
                f"[{account_id}] [{label}] 检测到折叠态「服务与承诺」，准备点击「展开修改」"
                f"（expandButton={section_state.get('expandButtonVisible')}）",
                flush=True,
            )

        expand_result: dict[str, Any] = {"ok": False}
        for attempt in range(3):
            if _is_shipping_form_ready(page):
                break
            expand_result = _click_expand_service_edit(page, account_id, label)
            page.run_js(_SCROLL_SERVICE_SECTION_JS)
            time.sleep(0.25)
            if _is_shipping_form_ready(page) or expand_result.get("formReady"):
                expand_result["ok"] = True
                break
            if attempt < 2:
                print(
                    f"[{account_id}] [{label}] 展开服务与承诺重试 ({attempt + 2}/3)...",
                    flush=True,
                )

        if not _is_shipping_form_ready(page):
            tab_result = _click_service_tab(page, account_id, label)
            page.run_js(_SCROLL_SERVICE_SECTION_JS)
            time.sleep(0.3)
            for _ in range(2):
                if _is_shipping_form_ready(page):
                    break
                expand_result = _click_expand_service_edit(page, account_id, label)
                time.sleep(0.5)
            if _is_shipping_form_ready(page):
                return {
                    "ok": True,
                    "method": "tab_then_expand",
                    "tab": tab_result.get("method"),
                    "expand": expand_result,
                }

        if _is_shipping_form_ready(page):
            print(f"[{account_id}] [{label}] 已展开服务与承诺，运费模板表单就绪", flush=True)
            return {"ok": True, "method": expand_result.get("method", "expanded"), "expand": expand_result}

        after = _detect_service_section(page)
        print(
            f"[{account_id}] [{label}] 运费模板表单仍不可用（展开修改可能未生效）；"
            f"expandButtonVisible={after.get('expandButtonVisible')} formReady={after.get('formReady')}",
            flush=True,
        )
        return {"ok": False, "reason": "shipping_form_not_ready", "expand": expand_result, "state": after}
    except Exception as exc:
        print(f"[{account_id}] [{label}] 准备服务与承诺区域异常：{_safe_exc(exc)}", flush=True)
        return {"ok": False, "reason": "exception", "error": _safe_exc(exc)}


def _pick_shipping_template_dropdown_playwright(
    page: DpPage,
) -> dict[str, Any]:
    """Playwright 打开运费模板下拉并选中目标项（Beast UI 需 evaluate 点击才生效）。"""
    raw = page._page
    candidates = list(flatten_shipping_template_candidates())

    service = raw.locator(".goods-service-v2, .goods-service").first
    if service.count() == 0:
        return {"ok": False, "reason": "service_section_not_found"}
    block = service.locator("div").filter(has_text="运费模板").filter(has_text="其他模板").last

    block.get_by_text("其他模板", exact=True).last.click(timeout=5000, force=True)
    time.sleep(0.6)

    header = block.locator('[data-testid="beast-core-select-header"]').last
    if header.count() == 0:
        header = block.locator('[data-testid*="select-header"]').last
    header.scroll_into_view_if_needed(timeout=3000)

    visible_options: list[str] = []
    last_error = ""

    for attempt in range(3):
        try:
            header.click(timeout=5000, force=True)
        except Exception as exc:
            last_error = _safe_exc(exc)
            continue
        time.sleep(0.8)

        portal = raw.locator('[data-testid="beast-core-portal-main"]').last
        try:
            portal.wait_for(state="visible", timeout=4000)
        except Exception as exc:
            last_error = _safe_exc(exc)
            raw.keyboard.press("Escape")
            time.sleep(0.2)
            continue

        beast_opts = portal.locator('[data-testid="beast-core-select-option"]')
        visible_options = []
        try:
            for idx in range(min(beast_opts.count(), 30)):
                text = (beast_opts.nth(idx).inner_text(timeout=500) or "").strip()
                if text:
                    visible_options.append(text)
        except Exception:
            pass

        for candidate in candidates:
            target = candidate.replace(" ", "")
            opt = None
            for idx in range(beast_opts.count()):
                try:
                    text = (beast_opts.nth(idx).inner_text(timeout=500) or "").strip()
                except Exception:
                    continue
                normalized = text.replace(" ", "")
                if normalized == target or (target and target in normalized):
                    opt = beast_opts.nth(idx)
                    break
            if opt is None:
                opt = portal.locator('[data-testid="beast-core-select-option"]').filter(
                    has_text=candidate
                ).first
            try:
                opt.scroll_into_view_if_needed(timeout=2000)
                opt.evaluate(
                    """(el) => {
                      el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true }));
                      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                      el.click();
                      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                      el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true }));
                    }"""
                )
                time.sleep(0.7)
                new_text = (header.inner_text(timeout=2000) or "").replace(" ", "")
                if target in new_text:
                    return {
                        "ok": True,
                        "method": "playwright_dropdown",
                        "template": candidate,
                        "selected": new_text,
                    }
            except Exception as exc:
                last_error = _safe_exc(exc)
                continue

        try:
            raw.keyboard.press("Escape")
            time.sleep(0.3)
        except Exception:
            pass

    return {
        "ok": False,
        "reason": "option_click_failed",
        "error": last_error,
        "visibleOptions": visible_options[:30],
    }


def _select_shipping_template_playwright(page: DpPage) -> dict[str, Any]:
    page.run_js(_SCROLL_SERVICE_SECTION_JS)
    time.sleep(0.2)
    page._page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    time.sleep(0.2)
    result = _pick_shipping_template_dropdown_playwright(page)
    if not result.get("ok"):
        return result
    state = _read_shipping_template_state(page)
    if shipping_state_matches_acceptable(str(state.get("current") or "")):
        return {**result, "state": state}
    return {"ok": False, "method": "playwright", "reason": "verify_failed", "state": state}


def _select_shipping_template(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    template_name: str,
    assume_form_ready: bool = False,
) -> dict[str, Any]:
    template_name = str(template_name or DEFAULT_SHIPPING_TEMPLATE).strip() or DEFAULT_SHIPPING_TEMPLATE
    try:
        state = _read_shipping_template_state(page)
        if not _shipping_state_is_valid(state):
            print(
                f"[{account_id}] [{label}] 运费模板状态无效或未展开，"
                f"found={state.get('found')} current={state.get('current') or '<空>'} "
                f"expandButton={state.get('expandButtonVisible')}",
                flush=True,
            )
            expand_result = _click_expand_service_edit(page, account_id, label)
            time.sleep(0.5)
            state = _read_shipping_template_state(page)
            if not _shipping_state_is_valid(state):
                print(
                    f"[{account_id}] [{label}] 展开后运费模板仍不可用；"
                    f"expand={expand_result.get('ok')} current={state.get('current') or '<空>'}",
                    flush=True,
                )
                return {
                    "ok": False,
                    "reason": "shipping_form_not_ready",
                    "state": state,
                    "expand": expand_result,
                }
        elif not assume_form_ready and not _is_shipping_form_ready(page):
            state = _read_shipping_template_state(page)
            print(
                f"[{account_id}] [{label}] 运费模板表单未就绪，无法选择模板；"
                f"found={state.get('found')} current={state.get('current') or '<空>'}",
                flush=True,
            )
            return {"ok": False, "reason": "shipping_form_not_ready", "state": state}
        matched_name = resolve_matched_template_name(str(state.get("current") or ""))
        if shipping_state_matches_acceptable(str(state.get("current") or "")) and state.get("otherChecked"):
            display = matched_name or str(state.get("current") or template_name)
            print(
                f"[{account_id}] [{label}] 运费模板已是「{display}」",
                flush=True,
            )
            return {"ok": True, "method": "already_set", "template": display, "state": state}

        time.sleep(0.3)
        try:
            page._page.keyboard.press("Escape")
            time.sleep(0.2)
        except Exception:
            pass

        try:
            pw_result = _pick_shipping_template_dropdown_playwright(page)
        except Exception as exc:
            pw_result = {"ok": False, "reason": "playwright_error", "error": _safe_exc(exc)}
        if pw_result.get("ok"):
            state = _read_shipping_template_state(page)
            selected = (
                resolve_matched_template_name(str(state.get("current") or ""))
                or str(state.get("current") or pw_result.get("template") or template_name)
            )
            print(
                f"[{account_id}] [{label}] 运费模板已选「其他模板」→「{selected}」"
                f"（Playwright）",
                flush=True,
            )
            return {**pw_result, "template": selected, "state": state}

        result: dict[str, Any] = {**pw_result, "ok": False, "reason": "template_not_selected"}
        for primary, aliases in iter_shipping_template_selection_attempts():
            raw = page.run_js(_SELECT_SHIPPING_TEMPLATE_JS, primary, list(aliases))
            candidate_result = _normalize_js_result(raw)
            time.sleep(0.5)
            state = _read_shipping_template_state(page)
            if candidate_result.get("ok") and shipping_state_matches_acceptable(
                str(state.get("current") or "")
            ):
                selected = resolve_matched_template_name(str(state.get("current") or "")) or primary
                print(
                    f"[{account_id}] [{label}] 运费模板已选「其他模板」→「{selected}」",
                    flush=True,
                )
                return {**candidate_result, "template": selected, "state": state}
            result = {**result, **candidate_result}

        state = _read_shipping_template_state(page)
        detail = (result.get("detail") or {}) if isinstance(result.get("detail"), dict) else {}
        visible = detail.get("visibleOptions") or result.get("visibleOptions") or []
        print(
            f"[{account_id}] [{label}] 运费模板设置失败："
            f"{result.get('step', result.get('reason', 'unknown'))}，"
            f"其他模板={'已选' if state.get('otherChecked') else '未选'}，"
            f"当前={state.get('current') or '<空>'}"
            + (f"，可见选项={visible[:8]}" if visible else ""),
            flush=True,
        )
        return {**result, "state": state}
    except Exception as exc:
        print(f"[{account_id}] [{label}] 运费模板设置异常：{_safe_exc(exc)}", flush=True)
        return {"ok": False, "reason": "exception", "error": _safe_exc(exc)}


def apply_listing_publish_settings(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    bulk_discount: str = DEFAULT_BULK_DISCOUNT,
    shipping_template: str = DEFAULT_SHIPPING_TEMPLATE,
) -> dict[str, Any]:
    """提交前设置满件折扣与运费模板；未完成则阻断提交。"""
    summary: dict[str, Any] = {
        "bulk_discount": _set_bulk_discount(
            page,
            account_id,
            label,
            discount=str(bulk_discount or DEFAULT_BULK_DISCOUNT).strip() or DEFAULT_BULK_DISCOUNT,
        ),
        "service_section": _ensure_service_section_ready(page, account_id, label),
    }
    template_name = (
        str(shipping_template or DEFAULT_SHIPPING_TEMPLATE).strip() or DEFAULT_SHIPPING_TEMPLATE
    )
    if summary["service_section"].get("ok") or _is_shipping_form_ready(page):
        summary["shipping_template"] = _select_shipping_template(
            page,
            account_id,
            label,
            template_name=template_name,
            assume_form_ready=bool(summary["service_section"].get("ok")),
        )
    else:
        summary["shipping_template"] = {
            "ok": False,
            "reason": "shipping_section_not_ready",
        }
    summary["ok"] = bool(
        summary["bulk_discount"].get("ok")
        and summary["shipping_template"].get("ok")
    )
    return summary

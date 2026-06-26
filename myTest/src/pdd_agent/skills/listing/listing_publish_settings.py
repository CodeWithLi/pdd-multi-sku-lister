"""上架提交前：满件折扣、服务与承诺（运费模板）页面设置。"""

from __future__ import annotations

import json
import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.listing.multi_spec_page import _safe_exc

DEFAULT_BULK_DISCOUNT = "9.9"
DEFAULT_SHIPPING_TEMPLATE = "最新全国"

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

_CLICK_EXPAND_SERVICE_EDIT_JS = """
function norm(text) {
  return String(text || '').replace(/\\s+/g, '');
}
function hasExpandButton() {
  for (const el of document.querySelectorAll('span,div,a,button,.text-v2,.bottom-switch')) {
    if (norm(el.textContent) === '展开修改') return true;
  }
  return false;
}
function findShippingBlock() {
  for (const el of document.querySelectorAll('label,div,span,th,td,section')) {
    const t = norm(el.textContent);
    if (t !== '运费模板' && !t.startsWith('运费模板')) continue;
    let node = el;
    for (let depth = 0; depth < 18 && node; depth++) {
      const ctx = norm(node.textContent);
      if (ctx.includes('运费模板') && ctx.includes('其他模板')) {
        return node;
      }
      node = node.parentElement;
    }
  }
  return null;
}
function clickExpandEdit() {
  try {
    window.scrollTo(0, document.documentElement.scrollHeight);
  } catch (e) {}
  const section = Array.from(document.querySelectorAll('div,section')).find((el) => {
    const t = (el.textContent || '').trim();
    return t.startsWith('3 服务与承诺') || t.includes('3服务与承诺');
  });
  if (section) {
    try { section.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
  }
  const candidates = [];
  for (const el of document.querySelectorAll('.bottom-switch, .text-v2, span, div, a, button')) {
    const t = norm(el.textContent);
    if (t === '展开修改' || t.endsWith('展开修改')) {
      candidates.push(el.closest('.bottom-switch') || el);
    }
  }
  for (const target of candidates) {
    try { target.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    target.click();
    target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    if (findShippingBlock() || !hasExpandButton()) {
      return { ok: true, method: 'force_click' };
    }
  }
  const tracked = document.querySelector(
    '[data-tracking-click-viewid*="expand_edit"], [data-tracking-click-viewid*="expand_modify"]'
  );
  if (tracked) {
    tracked.click();
    if (findShippingBlock() || !hasExpandButton()) {
      return { ok: true, method: 'tracking' };
    }
  }
  return { ok: false, reason: 'expand_button_not_found' };
}
return clickExpandEdit();
"""

_IS_SERVICE_EXPANDED_JS = """
function norm(text) {
  return String(text || '').replace(/\\s+/g, '');
}
function findShippingBlock() {
  for (const el of document.querySelectorAll('label,div,span,th,td,section')) {
    const t = norm(el.textContent);
    if (t !== '运费模板' && !t.startsWith('运费模板')) continue;
    let node = el;
    for (let depth = 0; depth < 18 && node; depth++) {
      const ctx = norm(node.textContent);
      if (ctx.includes('运费模板') && ctx.includes('其他模板')) {
        return true;
      }
      node = node.parentElement;
    }
  }
  return false;
}
function hasExpandButton() {
  for (const el of document.querySelectorAll('span,div,a,button,.text-v2,.bottom-switch')) {
    if (norm(el.textContent) === '展开修改') return true;
  }
  return false;
}
return { expanded: findShippingBlock() || !hasExpandButton(), hasExpandButton: hasExpandButton() };
"""

_FIND_SHIPPING_BLOCK_JS = """
function norm(text) {
  return String(text || '').replace(/\\s+/g, '');
}
function findShippingBlock() {
  for (const el of document.querySelectorAll('label,div,span,th,td,section')) {
    const t = norm(el.textContent);
    if (t !== '运费模板' && !t.startsWith('运费模板')) continue;
    let node = el;
    for (let depth = 0; depth < 18 && node; depth++) {
      const ctx = norm(node.textContent);
      if (ctx.includes('运费模板') && ctx.includes('其他模板')) {
        return node;
      }
      node = node.parentElement;
    }
  }
  for (const el of document.querySelectorAll('div,section')) {
    const t = norm(el.textContent);
    if (t.includes('运费模板') && t.includes('其他模板') && t.length < 5000) {
      return el;
    }
  }
  return null;
}
return findShippingBlock() ? { visible: true } : { visible: false };
"""

_READ_SHIPPING_TEMPLATE_JS = """
function norm(text) {
  return String(text || '').replace(/\\s+/g, '');
}
function findShippingBlock() {
  for (const el of document.querySelectorAll('label,div,span,th,td,section')) {
    const t = norm(el.textContent);
    if (t !== '运费模板' && !t.startsWith('运费模板')) continue;
    let node = el;
    for (let depth = 0; depth < 18 && node; depth++) {
      const ctx = norm(node.textContent);
      if (ctx.includes('运费模板') && ctx.includes('其他模板')) {
        return node;
      }
      node = node.parentElement;
    }
  }
  return null;
}
const block = findShippingBlock();
if (!block) return { found: false, current: '', otherChecked: false };
const header = block.querySelector(
  '[data-testid="beast-core-select-header"], [data-testid*="select-header"], [role="combobox"]'
);
const current = header ? norm(header.textContent) : '';
const otherChecked = Array.from(block.querySelectorAll(
  'label,[data-testid="beast-core-radio"],span,div'
)).some((el) => {
  const t = norm(el.textContent);
  if (t !== '其他模板' && !t.startsWith('其他模板')) return false;
  const radio = el.querySelector?.('input[type="radio"]')
    || el.closest('label')?.querySelector?.('input[type="radio"]');
  return radio ? radio.checked : false;
});
return { found: true, current, otherChecked };
"""

_SELECT_SHIPPING_TEMPLATE_JS = """
function norm(text) {
  return String(text || '').replace(/\\s+/g, '');
}
function findShippingBlock() {
  for (const el of document.querySelectorAll('label,div,span,th,td,section')) {
    const t = norm(el.textContent);
    if (t !== '运费模板' && !t.startsWith('运费模板')) continue;
    let node = el;
    for (let depth = 0; depth < 18 && node; depth++) {
      const ctx = norm(node.textContent);
      if (ctx.includes('运费模板') && ctx.includes('其他模板')) {
        return node;
      }
      node = node.parentElement;
    }
  }
  return null;
}
function clickRadioByText(scope, text) {
  const nodes = scope.querySelectorAll(
    'label,[data-testid="beast-core-radio"],span,div'
  );
  for (const el of nodes) {
    const t = norm(el.textContent);
    if (t !== text && !t.startsWith(text)) continue;
    const clickEl = el.closest('label')
      || el.closest('[data-testid="beast-core-radio"]')
      || el;
    clickEl.click();
    const radio = clickEl.querySelector?.('input[type="radio"]')
      || el.querySelector?.('input[type="radio"]');
    if (radio) {
      radio.checked = true;
      radio.dispatchEvent(new Event('change', { bubbles: true }));
      radio.click();
    }
    return true;
  }
  return false;
}
function selectDropdownOption(scope, optionText) {
  const header = scope.querySelector(
    '[data-testid="beast-core-select-header"], [data-testid*="select-header"], [role="combobox"]'
  );
  if (!header) return { ok: false, step: 'header_not_found' };
  header.click();
  const roots = [
    ...document.querySelectorAll('[data-testid="beast-core-portal-main"]'),
    document.body,
  ];
  for (const root of roots) {
    const options = root.querySelectorAll(
      '[data-testid="beast-core-select-option"], [role="option"], li, div, span'
    );
    for (const opt of options) {
      const t = (opt.textContent || '').trim();
      if (t === optionText || t.startsWith(optionText)) {
        opt.click();
        return { ok: true, selected: t };
      }
    }
  }
  return { ok: false, step: 'option_not_found', optionText };
}
function selectShipping(templateName) {
  const block = findShippingBlock();
  if (!block) return { ok: false, step: 'shipping_block_not_found' };
  try { block.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
  if (!clickRadioByText(block, '其他模板')) {
    return { ok: false, step: 'other_template_radio' };
  }
  const drop = selectDropdownOption(block, templateName);
  if (!drop.ok) return { ok: false, step: 'dropdown', detail: drop };
  return { ok: true, template: templateName, dropdown: drop };
}
return selectShipping(arguments[0]);
"""

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


def _is_shipping_template_visible(page: DpPage) -> bool:
    try:
        raw = page.run_js(_FIND_SHIPPING_BLOCK_JS)
        result = _normalize_js_result(raw)
        return bool(result.get("visible"))
    except Exception:
        return False


def _is_service_section_expanded(page: DpPage) -> bool:
    try:
        raw = page.run_js(_IS_SERVICE_EXPANDED_JS)
        result = _normalize_js_result(raw)
        return bool(result.get("expanded"))
    except Exception:
        return _is_shipping_template_visible(page)


def _read_shipping_template_state(page: DpPage) -> dict[str, Any]:
    try:
        return _normalize_js_result(page.run_js(_READ_SHIPPING_TEMPLATE_JS))
    except Exception:
        return {"found": False, "current": "", "otherChecked": False}


def _shipping_template_matches(state: dict[str, Any], template_name: str) -> bool:
    current = str(state.get("current") or "").replace(" ", "")
    target = str(template_name or "").replace(" ", "")
    return bool(target) and target in current


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
    page.run_js(_SCROLL_SERVICE_SECTION_JS)
    time.sleep(0.35)
    raw = page.run_js(_CLICK_EXPAND_SERVICE_EDIT_JS)
    result = _normalize_js_result(raw)
    if result.get("ok"):
        time.sleep(0.9)
        return result

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
            if _is_service_section_expanded(page):
                return {"ok": True, "method": "ele_js"}
        except Exception:
            pass

    try:
        page._page.evaluate(
            """
            () => {
              window.scrollTo(0, document.documentElement.scrollHeight);
              for (const el of document.querySelectorAll('.bottom-switch, .text-v2, span, div, a')) {
                const t = (el.textContent || '').replace(/\\s+/g, '');
                if (t !== '展开修改') continue;
                const target = el.closest('.bottom-switch') || el;
                target.click();
                return true;
              }
              return false;
            }
            """
        )
        time.sleep(0.9)
        if _is_service_section_expanded(page):
            return {"ok": True, "method": "playwright_eval"}
    except Exception:
        pass

    print(f"[{account_id}] [{label}] 未能点击「展开修改」", flush=True)
    return result or {"ok": False, "reason": "expand_button_not_found"}


def _ensure_service_section_ready(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    """在当前页滚到底部，展开「3 服务与承诺」，直到运费模板可选。"""
    try:
        page.run_js(_SCROLL_SERVICE_SECTION_JS)
        time.sleep(0.3)

        if _is_shipping_template_visible(page):
            print(f"[{account_id}] [{label}] 运费模板区域已可见", flush=True)
            return {"ok": True, "method": "already_visible"}

        expand_result: dict[str, Any] = {"ok": False}
        for attempt in range(3):
            if _is_shipping_template_visible(page) or _is_service_section_expanded(page):
                break
            expand_result = _click_expand_service_edit(page, account_id, label)
            page.run_js(_SCROLL_SERVICE_SECTION_JS)
            time.sleep(0.25)
            if _is_shipping_template_visible(page):
                break
            if attempt < 2:
                print(
                    f"[{account_id}] [{label}] 展开服务与承诺重试 ({attempt + 2}/3)...",
                    flush=True,
                )

        if not _is_shipping_template_visible(page):
            tab_result = _click_service_tab(page, account_id, label)
            page.run_js(_SCROLL_SERVICE_SECTION_JS)
            time.sleep(0.3)
            for _ in range(2):
                if _is_shipping_template_visible(page):
                    break
                _click_expand_service_edit(page, account_id, label)
                time.sleep(0.5)
            if _is_shipping_template_visible(page):
                return {
                    "ok": True,
                    "method": "tab_then_expand",
                    "tab": tab_result.get("method"),
                }

        if _is_shipping_template_visible(page):
            print(f"[{account_id}] [{label}] 已展开服务与承诺，运费模板可见", flush=True)
            return {"ok": True, "method": expand_result.get("method", "expanded")}

        print(
            f"[{account_id}] [{label}] 运费模板区域仍不可见（展开修改可能未生效）",
            flush=True,
        )
        return {"ok": False, "reason": "shipping_block_not_visible", "expand": expand_result}
    except Exception as exc:
        print(f"[{account_id}] [{label}] 准备服务与承诺区域异常：{_safe_exc(exc)}", flush=True)
        return {"ok": False, "reason": "exception", "error": _safe_exc(exc)}


def _select_shipping_template_playwright(page: DpPage, template_name: str) -> dict[str, Any]:
    raw = page._page
    page.run_js(_SCROLL_SERVICE_SECTION_JS)
    time.sleep(0.2)
    raw.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    time.sleep(0.2)

    block = raw.locator("div").filter(has_text="运费模板").filter(has_text="其他模板").last
    block.get_by_text("其他模板", exact=True).click(timeout=5000, force=True)
    time.sleep(0.5)
    header = block.locator('[data-testid="beast-core-select-header"]').first
    if header.count() == 0:
        header = raw.locator('[data-testid="beast-core-select-header"]').last
    header.click(timeout=5000, force=True)
    time.sleep(0.4)
    portal = raw.locator('[data-testid="beast-core-portal-main"]')
    option = portal.get_by_text(template_name, exact=True).first
    option.click(timeout=5000, force=True)
    time.sleep(0.3)
    state = _read_shipping_template_state(page)
    if _shipping_template_matches(state, template_name):
        return {"ok": True, "method": "playwright", "template": template_name, "state": state}
    return {"ok": False, "method": "playwright", "reason": "verify_failed", "state": state}


def _select_shipping_template(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    template_name: str,
) -> dict[str, Any]:
    template_name = str(template_name or DEFAULT_SHIPPING_TEMPLATE).strip() or DEFAULT_SHIPPING_TEMPLATE
    try:
        state = _read_shipping_template_state(page)
        if _shipping_template_matches(state, template_name) and state.get("otherChecked"):
            print(
                f"[{account_id}] [{label}] 运费模板已是「{template_name}」",
                flush=True,
            )
            return {"ok": True, "method": "already_set", "template": template_name, "state": state}

        time.sleep(0.3)
        raw = page.run_js(_SELECT_SHIPPING_TEMPLATE_JS, template_name)
        result = _normalize_js_result(raw)
        time.sleep(0.3)
        state = _read_shipping_template_state(page)
        if result.get("ok") and _shipping_template_matches(state, template_name):
            print(
                f"[{account_id}] [{label}] 运费模板已选「其他模板」→「{template_name}」",
                flush=True,
            )
            return {**result, "state": state}

        try:
            pw_result = _select_shipping_template_playwright(page, template_name)
            if pw_result.get("ok"):
                print(
                    f"[{account_id}] [{label}] 运费模板已选「其他模板」→「{template_name}」（Playwright）",
                    flush=True,
                )
                return pw_result
        except Exception as exc:
            result = {**result, "playwright_error": _safe_exc(exc)}

        print(
            f"[{account_id}] [{label}] 运费模板设置失败："
            f"{result.get('step', result.get('reason', 'unknown'))}，当前={state.get('current') or '<空>'}",
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
    if summary["service_section"].get("ok") or _is_shipping_template_visible(page):
        summary["shipping_template"] = _select_shipping_template(
            page,
            account_id,
            label,
            template_name=template_name,
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

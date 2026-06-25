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

_CLICK_EXPAND_SERVICE_EDIT_JS = """
function clickExpandEdit() {
  const tracked = document.querySelector(
    '[data-tracking-click-viewid*="expand_edit"], [data-tracking-viewid*="expand_modify"]'
  );
  if (tracked) {
    tracked.click();
    return { ok: true, method: 'tracking' };
  }
  for (const el of document.querySelectorAll('.bottom-switch .text-v2, .bottom-switch, .text-v2')) {
    if ((el.textContent || '').trim() === '展开修改') {
      (el.closest('.bottom-switch') || el).click();
      return { ok: true, method: 'bottom_switch' };
    }
  }
  for (const el of document.querySelectorAll('span,div,a,button')) {
    const t = (el.textContent || '').replace(/\\s+/g, '');
    if (t === '展开修改') {
      el.click();
      return { ok: true, method: 'text' };
    }
  }
  return { ok: false, reason: 'expand_button_not_found' };
}
return clickExpandEdit();
"""

_SELECT_SHIPPING_TEMPLATE_JS = """
function clickRadioByText(scope, text) {
  const nodes = scope.querySelectorAll(
    'label,[data-testid="beast-core-radio"],span,div'
  );
  for (const el of nodes) {
    const t = (el.textContent || '').replace(/\\s+/g, '');
    if (t !== text && !t.startsWith(text)) continue;
    const clickEl = el.closest('label')
      || el.closest('[data-testid="beast-core-radio"]')
      || el;
    clickEl.click();
    const radio = clickEl.querySelector?.('input[type="radio"]')
      || el.querySelector?.('input[type="radio"]');
    if (radio) radio.click();
    return true;
  }
  return false;
}
function visibleOptionRoots() {
  const roots = [
    ...document.querySelectorAll('[data-testid="beast-core-portal-main"]'),
    document.body,
  ];
  return roots.filter((el) => el && el.isConnected);
}
function selectDropdownOption(optionText) {
  const plate = document.querySelector(
    '#tm-plate, .goods-basic-line.template, .goods-basic-container, [class*="goods-basic"]'
  ) || document.body;
  const headers = Array.from(plate.querySelectorAll(
    '[data-testid="beast-core-select-header"], [data-testid*="select-header"], [role="combobox"]'
  )).filter((h) => {
    const ctx = (h.closest('div,section')?.textContent || '').replace(/\\s+/g, '');
    return ctx.includes('运费') || ctx.includes('模板') || ctx.includes('服务与承诺');
  });
  const header = headers[headers.length - 1]
    || Array.from(plate.querySelectorAll(
      '[data-testid="beast-core-select-header"], [data-testid*="select-header"], [role="combobox"]'
    )).pop();
  if (!header) return { ok: false, step: 'header_not_found' };
  header.click();
  const roots = visibleOptionRoots();
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
  const plate = document.querySelector(
    '#tm-plate, .goods-basic-line.template, .goods-basic-container, [class*="goods-basic"]'
  );
  const scope = plate || document;
  if (!clickRadioByText(scope, '其他模板') && !clickRadioByText(document, '其他模板')) {
    return { ok: false, step: 'other_template_radio' };
  }
  const drop = selectDropdownOption(templateName);
  if (!drop.ok) return { ok: false, step: 'dropdown', detail: drop };
  return { ok: true, template: templateName, dropdown: drop };
}
return selectShipping(arguments[0]);
"""

_SCROLL_SERVICE_SECTION_JS = """
for (const sel of ['#tm-plate', '.goods-basic-line.template', '.goods-basic-container']) {
  const el = document.querySelector(sel);
  if (el) {
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    return { ok: true, selector: sel };
  }
}
for (const el of document.querySelectorAll('div,section')) {
  const t = (el.textContent || '').trim();
  if (t.startsWith('3 服务与承诺') || t === '服务与承诺') {
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    return { ok: true, method: 'heading' };
  }
}
for (const el of document.querySelectorAll('span,div')) {
  if ((el.textContent || '').trim() === '展开修改') {
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    return { ok: true, method: 'expand_button' };
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


def _expand_service_section(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    try:
        page.run_js(_SCROLL_SERVICE_SECTION_JS)
        time.sleep(0.3)
        if page.ele("text:收起", timeout=0.5):
            return {"ok": True, "method": "already_expanded"}
        raw = page.run_js(_CLICK_EXPAND_SERVICE_EDIT_JS)
        result = _normalize_js_result(raw)
        if not result.get("ok"):
            btn = page.ele("text:展开修改", timeout=2)
            if btn:
                btn.click(by_js=True)
                result = {"ok": True, "method": "ele"}
        if not result.get("ok"):
            try:
                page._page.get_by_text("展开修改", exact=True).click(timeout=2000)
                result = {"ok": True, "method": "playwright"}
            except Exception:
                pass
        if result.get("ok"):
            time.sleep(0.8)
            print(f"[{account_id}] [{label}] 已展开服务与承诺", flush=True)
        else:
            print(
                f"[{account_id}] [{label}] 未找到「展开修改」：{result.get('reason', 'unknown')}",
                flush=True,
            )
        return result
    except Exception as exc:
        print(f"[{account_id}] [{label}] 展开服务与承诺异常：{_safe_exc(exc)}", flush=True)
        return {"ok": False, "reason": "exception", "error": _safe_exc(exc)}


def _select_shipping_template(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    template_name: str,
) -> dict[str, Any]:
    template_name = str(template_name or DEFAULT_SHIPPING_TEMPLATE).strip() or DEFAULT_SHIPPING_TEMPLATE
    try:
        time.sleep(0.4)
        raw = page.run_js(_SELECT_SHIPPING_TEMPLATE_JS, template_name)
        result = _normalize_js_result(raw)
        if result.get("ok"):
            print(
                f"[{account_id}] [{label}] 运费模板已选「其他模板」→「{template_name}」",
                flush=True,
            )
            return result
        other = page.ele("text:其他模板", timeout=2)
        if other:
            other.click(by_js=True)
            time.sleep(0.6)
            option = page.ele(f"text:{template_name}", timeout=2)
            if option:
                option.click(by_js=True)
                print(
                    f"[{account_id}] [{label}] 运费模板已选「其他模板」→「{template_name}」（元素点击）",
                    flush=True,
                )
                return {"ok": True, "method": "ele", "template": template_name}
            try:
                page._page.get_by_text(template_name, exact=False).last.click(timeout=2000)
                print(
                    f"[{account_id}] [{label}] 运费模板已选「{template_name}」（Playwright 点击）",
                    flush=True,
                )
                return {"ok": True, "method": "playwright", "template": template_name}
            except Exception:
                pass
        print(
            f"[{account_id}] [{label}] 运费模板设置失败：{result.get('step', result.get('reason', 'unknown'))}",
            flush=True,
        )
        return result
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
    """提交前设置满件折扣与运费模板；单步失败不阻断上架，仅记日志。"""
    summary: dict[str, Any] = {
        "bulk_discount": _set_bulk_discount(
            page,
            account_id,
            label,
            discount=str(bulk_discount or DEFAULT_BULK_DISCOUNT).strip() or DEFAULT_BULK_DISCOUNT,
        ),
        "expand_service": _expand_service_section(page, account_id, label),
    }
    if summary["expand_service"].get("ok"):
        summary["shipping_template"] = _select_shipping_template(
            page,
            account_id,
            label,
            template_name=str(shipping_template or DEFAULT_SHIPPING_TEMPLATE).strip()
            or DEFAULT_SHIPPING_TEMPLATE,
        )
    else:
        summary["shipping_template"] = {
            "ok": False,
            "reason": "service_section_not_expanded",
        }
    summary["ok"] = bool(
        summary["bulk_discount"].get("ok")
        and summary["shipping_template"].get("ok")
    )
    return summary

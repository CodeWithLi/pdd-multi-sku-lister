"""上架提交前：满件折扣、服务与承诺（运费模板）页面设置。"""

from __future__ import annotations

import json
import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.listing.multi_spec_page import _safe_exc

DEFAULT_BULK_DISCOUNT = "9.9"
DEFAULT_SHIPPING_TEMPLATE = "最新全国"

_SET_BULK_DISCOUNT_JS = """
function setInputValue(input, value) {
  input.focus();
  input.value = value;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  input.blur();
}
function setBulkDiscount(value) {
  const markers = ['满件折扣', '满2件'];
  for (const marker of markers) {
    for (const el of document.querySelectorAll('label,div,span,p,td')) {
      const t = (el.textContent || '').trim();
      if (!t.includes(marker) || t.length > 160) continue;
      let node = el;
      for (let depth = 0; depth < 12 && node; depth++) {
        const inputs = Array.from(node.querySelectorAll('input')).filter((inp) => {
          const type = (inp.type || 'text').toLowerCase();
          return !['hidden', 'file', 'checkbox', 'radio', 'button', 'submit'].includes(type);
        });
        const target = inputs.find((inp) => {
          const ph = inp.getAttribute('placeholder') || '';
          const v = String(inp.value || '').trim();
          return ph.includes('5.0') || ph.includes('9.9') || v === '9.5' || v === '9.9';
        }) || inputs[0];
        if (target) {
          const before = String(target.value || '').trim();
          setInputValue(target, value);
          return { ok: true, marker, before, after: String(target.value || '').trim() };
        }
        node = node.parentElement;
      }
    }
  }
  for (const input of document.querySelectorAll(
    'input[data-testid="beast-core-input-htmlInput"], input'
  )) {
    const ph = input.getAttribute('placeholder') || '';
    if (ph.includes('5.0') && ph.includes('9.9')) {
      const before = String(input.value || '').trim();
      setInputValue(input, value);
      return { ok: true, method: 'placeholder', before, after: String(input.value || '').trim() };
    }
  }
  return { ok: false, reason: 'discount_input_not_found' };
}
return setBulkDiscount(arguments[0]);
"""

_CLICK_EXPAND_SERVICE_EDIT_JS = """
function clickExpandEdit() {
  const tracked = document.querySelector('[data-tracking-click-viewid*="expand_edit"]');
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
  for (const el of document.querySelectorAll('span,div,a')) {
    if ((el.textContent || '').trim() === '展开修改') {
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
function selectDropdownOption(optionText) {
  const plate = document.querySelector('#tm-plate, .goods-basic-line.template') || document.body;
  const headers = Array.from(document.querySelectorAll(
    '[data-testid="beast-core-select-header"], [data-testid*="select-header"], [role="combobox"]'
  )).filter((h) => plate.contains(h));
  const header = headers[headers.length - 1];
  if (!header) return { ok: false, step: 'header_not_found' };
  header.click();
  const options = document.querySelectorAll(
    '[data-testid="beast-core-select-option"], [role="option"], li, div'
  );
  for (const opt of options) {
    const t = (opt.textContent || '').trim();
    if (t === optionText || t.startsWith(optionText)) {
      opt.click();
      return { ok: true, selected: t };
    }
  }
  return { ok: false, step: 'option_not_found', optionText };
}
function selectShipping(templateName) {
  const plate = document.querySelector('#tm-plate, .goods-basic-line.template');
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


def _set_bulk_discount(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    discount: str,
) -> dict[str, Any]:
    try:
        raw = page.run_js(_SET_BULK_DISCOUNT_JS, str(discount))
        result = _normalize_js_result(raw)
        if result.get("ok"):
            print(
                f"[{account_id}] [{label}] 满件折扣已设为 {discount}"
                f"（原值 {result.get('before', '-')}）",
                flush=True,
            )
            return result
        btn = page.ele("text:修改", timeout=1)
        if btn and "满" in str(page.html or ""):
            btn.click()
            time.sleep(0.4)
            raw = page.run_js(_SET_BULK_DISCOUNT_JS, str(discount))
            result = _normalize_js_result(raw)
            if result.get("ok"):
                print(f"[{account_id}] [{label}] 满件折扣已设为 {discount}（经修改入口）", flush=True)
                return result
        print(
            f"[{account_id}] [{label}] 未找到满件折扣输入框：{result.get('reason', 'unknown')}",
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
        if result.get("ok"):
            time.sleep(0.6)
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
    try:
        time.sleep(0.4)
        raw = page.run_js(_SELECT_SHIPPING_TEMPLATE_JS, str(template_name))
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
            time.sleep(0.5)
            option = page.ele(f"text:{template_name}", timeout=2)
            if option:
                option.click(by_js=True)
                print(
                    f"[{account_id}] [{label}] 运费模板已选「其他模板」→「{template_name}」（元素点击）",
                    flush=True,
                )
                return {"ok": True, "method": "ele", "template": template_name}
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

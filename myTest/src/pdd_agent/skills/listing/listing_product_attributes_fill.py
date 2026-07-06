"""拼多多发布页「商品属性」搜索下拉框填写（独立封装，供 upload 引用）。"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.listing.multi_spec_page import _safe_exc

NO_RESULT_PHRASES = frozenset(
    {
        "搜索无结果",
        "暂无数据",
        "无匹配结果",
        "无结果",
        "未找到相关",
    }
)

OPTION_SELECTORS = (
    '[data-testid="beast-core-select-option"]',
    ".ant-select-item-option-content",
    ".ant-select-item-option",
    '[class*="option-item"]',
    '[class*="SelectList"] [class*="option"]',
)

_SCROLL_PRODUCT_ATTRIBUTES_JS = """
for (const marker of ['商品属性', '填写率']) {
  for (const el of document.querySelectorAll('div,span,label,h3,h4')) {
    const t = (el.textContent || '').trim();
    if (!t.includes(marker) || t.length > 40) continue;
    try {
      el.scrollIntoView({ block: 'center', behavior: 'instant' });
    } catch (e) {}
    return { ok: true, marker };
  }
}
return { ok: false };
"""

_FIND_PROPERTY_INPUT_JS = """
(labelNeedle) => {
  const norm = (s) => String(s || '').replace(/\\s+/g, '');
  const needle = norm(labelNeedle);
  if (!needle) return { ok: false, reason: 'empty_label' };

  const labelMatches = (text) => {
    const t = norm(text);
    if (!t) return false;
    if (t === needle) return true;
    if (t.endsWith(needle) && t.length <= needle.length + 8) return true;
    if (needle.length >= 3 && t.includes(needle) && t.length <= needle.length + 10) return true;
    return false;
  };

  let scope = document.body;
  for (const h of document.querySelectorAll('div,span,label,h3,h4')) {
    const t = (h.textContent || '').trim();
    if (t === '商品属性' || t.startsWith('商品属性')) {
      const box = h.closest('[class*="section"], [class*="block"], [class*="card"], [class*="panel"]')
        || h.parentElement;
      if (box) scope = box;
      break;
    }
  }

  const candidates = scope.querySelectorAll('label, span, div, td, th, p');
  for (const el of candidates) {
    const rawText = (el.textContent || '').trim();
    if (!labelMatches(rawText)) continue;
    if (rawText.length > needle.length + 24) continue;

    let node = el;
    for (let depth = 0; depth < 12 && node; depth++) {
      const header = node.querySelector('[data-testid="beast-core-select-header"]');
      const combobox = node.querySelector('[role="combobox"]');
      const input = node.querySelector(
        'input[type="text"], input[type="search"], input:not([type="hidden"]):not([type="file"])'
      );
      const target = (header && header.querySelector('input')) || input || header || combobox;
      if (target) {
        const rect = target.getBoundingClientRect();
        if (rect.width > 8 && rect.height > 8) {
          try { target.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
          try { target.click(); } catch (e) {}
          try { target.focus(); } catch (e) {}
          return { ok: true, tag: target.tagName, className: String(target.className || '') };
        }
      }
      node = node.parentElement;
    }
  }
  return { ok: false, reason: 'not_found' };
}
"""

_TYPE_INTO_FOCUSED_INPUT_JS = """
(value) => {
  const text = String(value || '');
  const active = document.activeElement;
  let input = null;
  if (active && (active.tagName === 'INPUT' || active.getAttribute('role') === 'combobox')) {
    input = active;
  }
  if (!input) {
    input = document.querySelector(
      '[data-testid="beast-core-portal-main"] input[type="text"], '
      + '[data-testid="beast-core-portal-main"] input[type="search"], '
      + '[data-testid="beast-core-select-header"] input'
    );
  }
  if (!input) return { ok: false, reason: 'input_not_focused' };
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  try { input.focus(); } catch (e) {}
  setter.call(input, '');
  input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }));
  setter.call(input, text);
  input.dispatchEvent(new InputEvent('input', {
    bubbles: true,
    data: text,
    inputType: 'insertText',
  }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true, value: String(input.value || '').trim() };
}
"""


def _norm_text(value: str) -> str:
    return str(value or "").replace(" ", "").replace("\u3000", "").strip()


def _log(account_id: str, listing_label: str, message: str) -> None:
    prefix = f"[{account_id}]"
    if listing_label:
        prefix += f" [{listing_label}]"
    print(f"{prefix} {message}", flush=True)


def load_enabled_listing_product_attributes() -> list[dict[str, str]]:
    """读取 enabled 商品属性配置；MySQL 不可用时回退默认种子。"""
    try:
        from pdd_agent.db.repositories import list_listing_product_attributes, seed_listing_product_attributes
        from pdd_agent.db.session import is_database_available

        if is_database_available():
            seed_listing_product_attributes()
            rows = list_listing_product_attributes(enabled_only=True)
            items = [
                {
                    "field_key": row.field_key,
                    "label": row.label,
                    "selected_value": str(row.selected_value or "").strip(),
                }
                for row in rows
                if row.enabled and str(row.selected_value or "").strip()
            ]
            if items:
                return items
    except Exception:
        pass

    from pdd_agent.domain.listing_product_attributes import DEFAULT_LISTING_PRODUCT_ATTRIBUTES

    return [
        {
            "field_key": item.field_key,
            "label": item.label,
            "selected_value": item.selected_value,
        }
        for item in DEFAULT_LISTING_PRODUCT_ATTRIBUTES
        if item.enabled and item.selected_value
    ]


def _scroll_product_attributes_section(raw) -> None:
    try:
        raw.evaluate(_SCROLL_PRODUCT_ATTRIBUTES_JS)
    except Exception:
        pass
    time.sleep(0.25)


def _focus_property_field(raw, label: str) -> dict[str, Any]:
    try:
        result = raw.evaluate(_FIND_PROPERTY_INPUT_JS, label)
        return result if isinstance(result, dict) else {"ok": False, "reason": "invalid_result"}
    except Exception as exc:
        return {"ok": False, "reason": "exception", "error": _safe_exc(exc)}


def _type_property_value(raw, value: str) -> dict[str, Any]:
    try:
        result = raw.evaluate(_TYPE_INTO_FOCUSED_INPUT_JS, value)
        return result if isinstance(result, dict) else {"ok": False, "reason": "invalid_result"}
    except Exception as exc:
        return {"ok": False, "reason": "exception", "error": _safe_exc(exc)}


def _collect_portal_options(portal) -> list[tuple[int, str, str]]:
    collected: list[tuple[int, str, str]] = []
    for selector in OPTION_SELECTORS:
        opts = portal.locator(selector)
        count = opts.count()
        if count <= 0:
            continue
        for idx in range(min(count, 50)):
            try:
                text = (opts.nth(idx).inner_text(timeout=250) or "").strip()
            except Exception:
                continue
            if not text or text in NO_RESULT_PHRASES:
                continue
            if "更多" in text and "搜索" in text:
                continue
            collected.append((idx, text, selector))
        if collected:
            break
    return collected


def _portal_only_shows_no_result(portal) -> bool:
    try:
        body = (portal.inner_text(timeout=300) or "").strip()
    except Exception:
        return False
    if not body:
        return False
    if any(phrase in body for phrase in NO_RESULT_PHRASES):
        return not _collect_portal_options(portal)
    return False


def _click_portal_option(portal, idx: int, selector: str) -> None:
    opt = portal.locator(selector).nth(idx)
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


def _wait_and_pick_dropdown_option(raw, value: str, *, max_wait_s: float = 15.0) -> dict[str, Any]:
    target = _norm_text(value)
    deadline = time.time() + max_wait_s
    last_options: list[str] = []

    while time.time() < deadline:
        portals = raw.locator('[data-testid="beast-core-portal-main"]')
        if portals.count() <= 0:
            time.sleep(0.35)
            continue

        portal = portals.last
        try:
            if not portal.is_visible():
                time.sleep(0.35)
                continue
        except Exception:
            time.sleep(0.35)
            continue

        if _portal_only_shows_no_result(portal):
            time.sleep(0.45)
            continue

        options = _collect_portal_options(portal)
        if not options:
            time.sleep(0.4)
            continue

        last_options = [text for _, text, _ in options[:12]]

        for idx, text, selector in options:
            normalized = _norm_text(text)
            if normalized == target or (target and target in normalized):
                try:
                    _click_portal_option(portal, idx, selector)
                    time.sleep(0.35)
                    return {"ok": True, "picked": text}
                except Exception as exc:
                    return {"ok": False, "reason": "click_failed", "error": _safe_exc(exc)}

        for idx, text, selector in options:
            normalized = _norm_text(text)
            if target and normalized in target:
                try:
                    _click_portal_option(portal, idx, selector)
                    time.sleep(0.35)
                    return {"ok": True, "picked": text, "fuzzy": True}
                except Exception as exc:
                    return {"ok": False, "reason": "click_failed", "error": _safe_exc(exc)}

        return {"ok": False, "reason": "option_not_found", "options": last_options}

    return {"ok": False, "reason": "timeout", "options": last_options}


def fill_listing_product_attribute_field(
    page: DpPage,
    *,
    account_id: str,
    label: str,
    value: str,
    listing_label: str = "",
    max_wait_s: float = 15.0,
) -> dict[str, Any]:
    """填写单个商品属性搜索下拉框。"""
    raw = page._page
    value = str(value or "").strip()
    label = str(label or "").strip()
    if not label or not value:
        return {"ok": False, "reason": "empty_label_or_value", "label": label}

    _scroll_product_attributes_section(raw)
    focus_result = _focus_property_field(raw, label)
    if not focus_result.get("ok"):
        return {"ok": False, "reason": focus_result.get("reason", "field_not_found"), "label": label}

    time.sleep(0.25)
    type_result = _type_property_value(raw, value)
    if not type_result.get("ok"):
        try:
            raw.keyboard.press("Control+A")
            raw.keyboard.type(value, delay=35)
        except Exception as exc:
            return {
                "ok": False,
                "reason": "type_failed",
                "label": label,
                "error": _safe_exc(exc),
            }

    time.sleep(0.35)
    pick_result = _wait_and_pick_dropdown_option(raw, value, max_wait_s=max_wait_s)
    if pick_result.get("ok"):
        _log(account_id, listing_label, f"商品属性「{label}」→ {pick_result.get('picked')}")
        return {"ok": True, "label": label, "value": value, **pick_result}

    try:
        raw.keyboard.press("Escape")
    except Exception:
        pass

    return {
        "ok": False,
        "label": label,
        "value": value,
        "reason": pick_result.get("reason", "pick_failed"),
        "options": pick_result.get("options") or [],
    }


def fill_listing_product_attributes(
    page: DpPage,
    account_id: str,
    *,
    listing_label: str = "",
    attributes: list[dict[str, str]] | None = None,
    max_wait_s: float = 15.0,
) -> dict[str, Any]:
    """
    填完标题后调用：按数据库/默认配置填写商品属性区所有 enabled 字段。
    跳过 是否透明 / 是否有夹层 / 产品类型（DB 中 enabled=false）。
    """
    items = attributes if attributes is not None else load_enabled_listing_product_attributes()
    if not items:
        return {"ok": False, "reason": "no_attributes_configured", "filled": [], "failed": []}

    _log(account_id, listing_label, f"开始填写商品属性（共 {len(items)} 项）…")
    _scroll_product_attributes_section(page._page)
    time.sleep(0.3)

    filled: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for item in items:
        label = str(item.get("label") or "").strip()
        value = str(item.get("selected_value") or "").strip()
        if not label or not value:
            continue

        result = fill_listing_product_attribute_field(
            page,
            account_id=account_id,
            label=label,
            value=value,
            listing_label=listing_label,
            max_wait_s=max_wait_s,
        )
        if result.get("ok"):
            filled.append(result)
        else:
            failed.append(result)
            _log(
                account_id,
                listing_label,
                f"商品属性「{label}」填写失败：{result.get('reason')} "
                f"options={result.get('options') or []}",
            )
        time.sleep(0.25)

    ok = len(failed) == 0
    summary = {
        "ok": ok,
        "filled_count": len(filled),
        "failed_count": len(failed),
        "filled": filled,
        "failed": failed,
    }
    _log(
        account_id,
        listing_label,
        f"商品属性填写完成：成功 {len(filled)}，失败 {len(failed)}",
    )
    return summary

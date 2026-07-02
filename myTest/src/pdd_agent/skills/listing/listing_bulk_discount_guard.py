"""
提交前满件折扣 Guard：核验页面是否已为 9.9 折，未填则补填并重试验证。

独立于 listing_publish_settings 原有流程，仅在上架提交前作为安全网调用。
"""

from __future__ import annotations

import re
import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.listing.listing_publish_settings import (
    DEFAULT_BULK_DISCOUNT,
    _read_bulk_discount_value,
    _set_bulk_discount,
)
from pdd_agent.skills.listing.multi_spec_page import _safe_exc

_LOG_TAG = "满件折扣Guard"
_VISIBLE_DISCOUNT_RE = re.compile(r"满2件\s*(\d+(?:\.\d+)?)\s*折")

_READ_VISIBLE_BULK_DISCOUNT_JS = """
function readVisibleBulkDiscount() {
  for (const el of document.querySelectorAll('label,div,span,p,td,th,section')) {
    const t = (el.textContent || '').trim();
    if (!t.includes('满2件') || t.length > 120) continue;
    const m = t.match(/满2件\\s*(\\d+(?:\\.\\d+)?)\\s*折/);
    if (m) return m[1];
  }
  const body = document.body?.innerText || '';
  const m2 = body.match(/满2件\\s*(\\d+(?:\\.\\d+)?)\\s*折/);
  return m2 ? m2[1] : '';
}
return readVisibleBulkDiscount();
"""

_CLICK_BULK_DISCOUNT_EDIT_JS = """
function clickBulkDiscountEdit() {
  const markers = ['满2件折扣', '满件折扣', '满2件'];
  for (const marker of markers) {
    for (const el of document.querySelectorAll('label,div,span,p,td,th,section')) {
      const t = (el.textContent || '').trim();
      if (!t.includes(marker) || t.length > 220) continue;
      let node = el;
      for (let depth = 0; depth < 14 && node; depth++) {
        for (const btn of node.querySelectorAll('a,button,span,div')) {
          const tx = (btn.textContent || '').replace(/\\s+/g, '');
          if (tx !== '修改' && !tx.endsWith('修改')) continue;
          try { btn.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
          btn.click();
          return { ok: true, marker, method: 'scoped_edit' };
        }
        node = node.parentElement;
      }
    }
  }
  return { ok: false, reason: 'bulk_discount_edit_not_found' };
}
return clickBulkDiscountEdit();
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


def parse_visible_bulk_discount(text: str) -> str:
    """从页面文本解析「满2件 X 折」中的折扣值。"""
    match = _VISIBLE_DISCOUNT_RE.search(str(text or ""))
    return match.group(1) if match else ""


def _guard_log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] [{_LOG_TAG}] {message}", flush=True)


def read_bulk_discount_state(page: DpPage) -> dict[str, str]:
    """同时读取 input 值与页面上可见的「满2件 X 折」文案。"""
    input_value = ""
    visible_value = ""
    try:
        input_value = str(_read_bulk_discount_value(page) or "").strip()
    except Exception:
        pass
    try:
        raw = page.run_js(_READ_VISIBLE_BULK_DISCOUNT_JS)
        visible_value = str(raw or "").strip()
    except Exception:
        pass
    return {
        "input_value": input_value,
        "visible_value": visible_value,
    }


def is_bulk_discount_verified(state: dict[str, str], *, target: str) -> bool:
    """input 与可见文案均指向目标折扣时才算通过。"""
    target = str(target or DEFAULT_BULK_DISCOUNT).strip()
    input_value = str(state.get("input_value") or "").strip()
    visible_value = str(state.get("visible_value") or "").strip()
    if input_value != target:
        return False
    if visible_value and visible_value != target:
        return False
    return True


def _scroll_bulk_discount_section(page: DpPage) -> None:
    try:
        page.run_js(_SCROLL_BULK_DISCOUNT_JS)
    except Exception:
        pass
    time.sleep(0.35)


def _click_bulk_discount_edit(page: DpPage) -> dict[str, Any]:
    try:
        raw = page.run_js(_CLICK_BULK_DISCOUNT_EDIT_JS)
        if isinstance(raw, dict) and raw.get("ok"):
            time.sleep(0.45)
            return raw
    except Exception:
        pass
    return {"ok": False, "reason": "bulk_discount_edit_not_found"}


def _attempt_fill_bulk_discount(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    discount: str,
    attempt: int,
) -> dict[str, Any]:
    _guard_log(account_id, label, f"第 {attempt} 次补填：滚动至满件折扣区域")
    _scroll_bulk_discount_section(page)

    before = read_bulk_discount_state(page)
    _guard_log(
        account_id,
        label,
        f"第 {attempt} 次补填前：input={before.get('input_value') or '<空>'}，"
        f"可见文案={before.get('visible_value') or '<空>'}",
    )

    edit_result = _click_bulk_discount_edit(page)
    if edit_result.get("ok"):
        _guard_log(
            account_id,
            label,
            f"第 {attempt} 次：已点击满件折扣区「修改」（{edit_result.get('marker', '-')}）",
        )
    else:
        _guard_log(account_id, label, f"第 {attempt} 次：未找到满件折扣区「修改」，直接尝试写入")

    fill_result = _set_bulk_discount(page, account_id, label, discount=discount)
    fill_result["attempt"] = attempt
    fill_result["before_state"] = before

    after = read_bulk_discount_state(page)
    fill_result["after_state"] = after
    fill_result["verified_strict"] = is_bulk_discount_verified(after, target=discount)
    fill_result["ok"] = bool(fill_result.get("verified_strict"))

    _guard_log(
        account_id,
        label,
        f"第 {attempt} 次补填后：input={after.get('input_value') or '<空>'}，"
        f"可见文案={after.get('visible_value') or '<空>'}，"
        f"严格校验={'通过' if fill_result['verified_strict'] else '未通过'}",
    )
    return fill_result


def ensure_bulk_discount_before_submit(
    page: DpPage,
    account_id: str,
    label: str,
    publish_settings: dict[str, Any],
    *,
    discount: str = DEFAULT_BULK_DISCOUNT,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """
    提交前核验满件折扣；若未达目标值则补填并重试。

    返回更新后的 publish_settings（仅更新 bulk_discount 与 ok 字段）。
    """
    discount = str(discount or DEFAULT_BULK_DISCOUNT).strip() or DEFAULT_BULK_DISCOUNT
    settings = dict(publish_settings or {})
    bulk = dict(settings.get("bulk_discount") or {})

    state = read_bulk_discount_state(page)
    _guard_log(
        account_id,
        label,
        f"提交前核验：目标={discount}，input={state.get('input_value') or '<空>'}，"
        f"可见文案={state.get('visible_value') or '<空>'}",
    )

    if is_bulk_discount_verified(state, target=discount):
        _guard_log(account_id, label, f"已确认为 {discount} 折，无需补填")
        bulk["ok"] = True
        bulk["after"] = discount
        bulk["verified_strict"] = True
        bulk["guard"] = "already_ok"
        settings["bulk_discount"] = bulk
        settings["ok"] = bool(bulk.get("ok") and (settings.get("shipping_template") or {}).get("ok"))
        return settings

    _guard_log(
        account_id,
        label,
        f"未达到 {discount} 折（input={state.get('input_value') or '<空>'}，"
        f"可见={state.get('visible_value') or '<空>'}），开始 Guard 补填（最多 {max_attempts} 次）",
    )

    last_result: dict[str, Any] = {
        "ok": False,
        "reason": "guard_not_started",
        "guard": "fill_failed",
    }
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            last_result = _attempt_fill_bulk_discount(
                page,
                account_id,
                label,
                discount=discount,
                attempt=attempt,
            )
        except Exception as exc:
            last_result = {
                "ok": False,
                "reason": "exception",
                "error": _safe_exc(exc),
                "attempt": attempt,
                "guard": "fill_failed",
            }
            _guard_log(account_id, label, f"第 {attempt} 次补填异常：{_safe_exc(exc)}")

        if last_result.get("verified_strict"):
            _guard_log(account_id, label, f"Guard 补填成功：第 {attempt} 次严格校验通过")
            bulk = {**bulk, **last_result, "ok": True, "guard": "filled_ok"}
            settings["bulk_discount"] = bulk
            settings["ok"] = bool(bulk.get("ok") and (settings.get("shipping_template") or {}).get("ok"))
            return settings

        if attempt < max_attempts:
            _guard_log(account_id, label, f"第 {attempt} 次未通过，等待 0.6s 后重试")
            time.sleep(0.6)

    final_state = read_bulk_discount_state(page)
    _guard_log(
        account_id,
        label,
        f"Guard 补填失败：已达最大次数 {max_attempts}，"
        f"最终 input={final_state.get('input_value') or '<空>'}，"
        f"可见文案={final_state.get('visible_value') or '<空>'}",
    )
    bulk = {
        **bulk,
        **last_result,
        "ok": False,
        "reason": last_result.get("reason") or "guard_verify_failed",
        "guard": "fill_failed",
        "final_state": final_state,
    }
    settings["bulk_discount"] = bulk
    settings["ok"] = bool(bulk.get("ok") and (settings.get("shipping_template") or {}).get("ok"))
    return settings

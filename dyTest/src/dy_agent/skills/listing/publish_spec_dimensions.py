"""抖店规格维度填表：颜色分类 / 尺寸大小（创建类型 → 输入 → 勾 → 确定）。"""

from __future__ import annotations

import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

COLOR_DIMENSION = "颜色分类"
SIZE_DIMENSION = "尺寸大小"
CREATE_TYPE_TEXT = "创建类型"
SPEC_VALUE_PLACEHOLDER = "请输入规格值"
CONFIRM_CHECK_WAIT_SECONDS = 0.8
COLOR_FAMILY_TABS = (
    "褐色系",
    "黄色系",
    "灰色系",
    "白色系",
    "红色系",
    "绿色系",
    "蓝色系",
    "黑色系",
    "紫色系",
    "粉色系",
    "橙色系",
)

_SPEC_SLOT_CORE = """
function __specVisible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 2 && r.height > 2 && s.display !== 'none' && s.visibility !== 'hidden';
}
function __slotKey(el) {
  const r = el.getBoundingClientRect();
  return Math.round(r.top) + ':' + Math.round(r.left);
}
function __isFilledSlot(el) {
  if (!el) return false;
  if (el.tagName === 'INPUT') {
    return !!(el.value || '').trim();
  }
  const inp = el.querySelector('input');
  if (inp && (inp.value || '').trim()) return true;
  const items = el.querySelectorAll(
    '.ecom-g-cascader-selection-item, .ant-select-selection-item, [class*="selection-item"]'
  );
  for (const item of items) {
    const t = (item.innerText || item.textContent || '').trim();
    if (t && !t.includes('请选择') && !t.includes('输入') && !t.includes('备注')) return true;
  }
  const search = el.querySelector('.ecom-g-cascader-selection-search input');
  if (search && (search.value || '').trim()) return true;
  const compact = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
  if (compact && !compact.includes('请选择') && !compact.includes('输入')
      && !compact.includes('备注') && compact.length <= 24) {
    return true;
  }
  return false;
}
function __collectSpecSlots(root) {
  const slots = [];
  const seen = new Set();
  for (const picker of root.querySelectorAll(
    '.ecom-g-cascader-picker, [class*="cascader-picker"]'
  )) {
    if (!__specVisible(picker)) continue;
    const key = __slotKey(picker);
    if (seen.has(key)) continue;
    seen.add(key);
    slots.push(picker);
  }
  for (const inp of root.querySelectorAll('input')) {
    const ph = (inp.getAttribute('placeholder') || '').trim();
    if (!__specVisible(inp)) continue;
    if (!(ph.includes('请选择') || ph.includes('输入'))) continue;
    const picker = inp.closest('.ecom-g-cascader-picker, [class*="cascader-picker"]');
    if (picker) {
      const key = __slotKey(picker);
      if (!seen.has(key) && __specVisible(picker)) {
        seen.add(key);
        slots.push(picker);
      }
      continue;
    }
    if ((inp.value || '').trim()) continue;
    const key = __slotKey(inp);
    if (seen.has(key)) continue;
    seen.add(key);
    slots.push(inp);
  }
  slots.sort((a, b) => {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    const topDiff = ra.top - rb.top;
    if (Math.abs(topDiff) > 12) return topDiff;
    return ra.left - rb.left;
  });
  return slots;
}
function __getRightmostEmptySlot(root) {
  const empty = __collectSpecSlots(root).filter((s) => !__isFilledSlot(s));
  if (!empty.length) return null;
  empty.sort((a, b) => {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    const topDiff = ra.top - rb.top;
    if (Math.abs(topDiff) > 12) return topDiff;
    return ra.left - rb.left;
  });
  return empty[empty.length - 1];
}
function __activateSlot(el) {
  try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
  try { el.focus(); } catch (e) {}
  el.click();
  const inp = el.tagName === 'INPUT' ? el : el.querySelector('input');
  if (inp) {
    try { inp.focus(); inp.click(); } catch (e) {}
  }
}
function __openSlotDropdown(el) {
  const root = el.closest('.ecom-g-cascader-picker, [class*="cascader-picker"]') || el;
  const arrow = root.querySelector(
    '.ecom-g-cascader-picker-arrow, .anticon-down, [aria-label="down"], span[role="img"]'
  );
  if (arrow) {
    arrow.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    arrow.click();
    return true;
  }
  root.click();
  return true;
}
function __fillSlotInput(el, val) {
  const inp = el.tagName === 'INPUT' ? el : el.querySelector('input');
  if (!inp) return false;
  __activateSlot(el);
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  if (setter) setter.call(inp, val);
  else inp.value = val;
  inp.dispatchEvent(new InputEvent('input', {
    bubbles: true, data: val, inputType: 'insertText'
  }));
  inp.dispatchEvent(new Event('change', { bubbles: true }));
  inp.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
  }));
  inp.dispatchEvent(new KeyboardEvent('keyup', {
    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
  }));
  try { inp.blur(); } catch (e) {}
  return (inp.value || '').trim() === val;
}
"""


def _spec_slot_eval(body: str) -> str:
    """Playwright evaluate 需要单个函数表达式，将 helper 包在内部。"""
    return f"(arg) => {{\n{_SPEC_SLOT_CORE}\n{body}\n}}"


def _spec_value_candidates(value: str) -> list[str]:
    """生成规格值候选（如 卡其 ↔ 卡其色），便于匹配抖店预设项。"""
    text = str(value or "").strip()
    if not text:
        return []
    candidates = [text]
    if not text.endswith("色"):
        candidates.append(f"{text}色")
    elif len(text) > 1:
        candidates.append(text[:-1])
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _scroll_spec_section(page: Page) -> None:
    try:
        page.evaluate(
            """
            () => {
              for (const el of document.querySelectorAll('*')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (t === '规格设置' || t.includes('规格设置')) {
                  el.scrollIntoView({ block: 'center', behavior: 'instant' });
                  return;
                }
              }
            }
            """
        )
    except Exception:
        pass
    time.sleep(0.3)


def _find_dimension_block_root(page: Page, dimension_label: str):
    """返回单个规格维度（颜色分类 / 尺寸大小）的独立 DOM 块，避免误操作相邻维度。"""
    return page.evaluate_handle(
        """
        (dimensionLabel) => {
          const allDims = ['颜色分类', '尺寸大小'];
          function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 20 && r.height > 8 && s.display !== 'none' && s.visibility !== 'hidden';
          }
          const labelEls = Array.from(document.querySelectorAll('*')).filter((el) => {
            if (!visible(el)) return false;
            const t = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
            return t === dimensionLabel;
          });
          labelEls.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);

          for (const labelEl of labelEls) {
            let node = labelEl;
            for (let depth = 0; depth < 12 && node; depth++) {
              const text = (node.innerText || node.textContent || '').replace(/\\s+/g, '');
              const hasOther = allDims
                .filter((d) => d !== dimensionLabel)
                .some((d) => text.includes(d));
              const hasControl = !!node.querySelector(
                'input[placeholder*="请选择"], input[placeholder*="输入"], '
                + '.ecom-g-cascader-picker, [class*="cascader-picker"]'
              );
              if (hasControl && !hasOther) {
                return node;
              }
              node = node.parentElement;
            }
          }
          return null;
        }
        """,
        dimension_label,
    )


def _find_spec_section_root(page: Page, dimension_label: str):
    """兼容旧名：返回规格维度独立块。"""
    return _find_dimension_block_root(page, dimension_label)


def _click_picker_arrow_in_section(page: Page, dimension_label: str, picker_index: int = 0) -> bool:
    handle = _find_dimension_block_root(page, dimension_label)
    if not handle:
        return False
    try:
        clicked = page.evaluate(
            """
            ([root, pickerIndex]) => {
              if (!root) return false;
              const pickers = Array.from(
                root.querySelectorAll('.ecom-g-cascader-picker, [class*="cascader-picker"]')
              );
              let target = pickers[pickerIndex] || pickers[0] || pickers[pickers.length - 1];
              if (!target) {
                const inp = root.querySelector(
                  'input[placeholder*="颜色"], input[placeholder*="尺寸"], input[placeholder*="规格"], '
                  + 'input[placeholder*="请选择"], input[placeholder*="输入"]'
                );
                if (inp) {
                  inp.focus();
                  inp.click();
                  return true;
                }
                return false;
              }
              const arrow = target.querySelector(
                '.ecom-g-cascader-picker-arrow, .anticon-down, [aria-label="down"], span[role="img"]'
              );
              if (arrow) {
                arrow.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                arrow.click();
                return true;
              }
              target.click();
              return true;
            }
            """,
            [handle, picker_index],
        )
        return bool(clicked)
    finally:
        try:
            handle.dispose()
        except Exception:
            pass


def _activate_rightmost_empty_slot(page: Page, dimension_label: str) -> bool:
    """点击维度行最右侧尚未填写的规格槽（抖店在后方追加空槽）。"""
    handle = _find_dimension_block_root(page, dimension_label)
    if not handle:
        return False
    try:
        return bool(
            page.evaluate(
                _spec_slot_eval(
                    """
                  const root = arg;
                  if (!root) return false;
                  const slot = __getRightmostEmptySlot(root);
                  if (!slot) return false;
                  __activateSlot(slot);
                  return true;
                    """
                ),
                handle,
            )
        )
    finally:
        try:
            handle.dispose()
        except Exception:
            pass


def _open_rightmost_empty_slot_dropdown(page: Page, dimension_label: str) -> bool:
    """在最右侧空槽上打开下拉（仅作用于该槽，不碰已填槽位）。"""
    handle = _find_dimension_block_root(page, dimension_label)
    if not handle:
        return False
    try:
        return bool(
            page.evaluate(
                _spec_slot_eval(
                    """
                  const root = arg;
                  if (!root) return false;
                  const slot = __getRightmostEmptySlot(root);
                  if (!slot) return false;
                  __activateSlot(slot);
                  return __openSlotDropdown(slot);
                    """
                ),
                handle,
            )
        )
    finally:
        try:
            handle.dispose()
        except Exception:
            pass


def _react_fill_inline_spec_in_block(
    page: Page,
    dimension_label: str,
    value: str,
    *,
    index: int = 0,
) -> bool:
    """手动规格 UI：在最右侧空槽输入并回车。"""
    if index > 0 and not _wait_for_spec_value_slot(page, dimension_label, index):
        return False

    handle = _find_dimension_block_root(page, dimension_label)
    if not handle:
        return False
    try:
        return bool(
            page.evaluate(
                _spec_slot_eval(
                    """
                  const [root, val] = arg;
                  if (!root || !val) return false;
                  const slot = __getRightmostEmptySlot(root);
                  if (!slot) return false;
                  return __fillSlotInput(slot, val);
                    """
                ),
                [handle, value],
            )
        )
    finally:
        try:
            handle.dispose()
        except Exception:
            pass


def _wait_for_spec_value_slot(page: Page, dimension_label: str, slot_index: int, *, max_wait: int = 20) -> bool:
    """等待右侧出现新的空规格槽（已填数量 >= slot_index）。"""
    for _ in range(max_wait):
        ready = page.evaluate(
            _spec_slot_eval(
                """
              const [dimensionLabel, slotIndex] = arg;
              const allDims = ['颜色分类', '尺寸大小'];
              function findRoot() {
                const labelEls = Array.from(document.querySelectorAll('*')).filter((el) => {
                  if (!__specVisible(el)) return false;
                  const t = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
                  return t === dimensionLabel;
                });
                labelEls.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
                for (const labelEl of labelEls) {
                  let node = labelEl;
                  for (let depth = 0; depth < 12 && node; depth++) {
                    const text = (node.innerText || node.textContent || '').replace(/\\s+/g, '');
                    const hasOther = allDims.filter((d) => d !== dimensionLabel).some((d) => text.includes(d));
                    const hasControl = !!node.querySelector(
                      'input[placeholder*="请选择"], input[placeholder*="输入"], '
                      + '.ecom-g-cascader-picker, [class*="cascader-picker"]'
                    );
                    if (hasControl && !hasOther) return node;
                    node = node.parentElement;
                  }
                }
                return null;
              }
              const root = findRoot();
              if (!root) return false;
              const slots = __collectSpecSlots(root);
              const filled = slots.filter((s) => __isFilledSlot(s)).length;
              const empty = __getRightmostEmptySlot(root);
              return filled >= slotIndex && !!empty;
                """
            ),
            [dimension_label, slot_index],
        )
        if ready:
            return True
        time.sleep(0.35)
    return False


def _focus_spec_input_slot(page: Page, dimension_label: str, index: int) -> bool:
    return _activate_rightmost_empty_slot(page, dimension_label)


def _is_manual_inline_spec_ui(page: Page) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                () => Array.from(document.querySelectorAll('input')).some((inp) => {
                  const ph = (inp.getAttribute('placeholder') || '').trim();
                  return ph.includes('请选择') && ph.includes('输入');
                })
                """
            )
        )
    except Exception:
        return False


def _click_create_type_in_popup(page: Page) -> bool:
    """点击弹层底部「无合适选项？创建类型」（styles_newSKU__o94gg）。"""
    playwright_selectors = [
        '[class*="newSKU"]:has-text("创建类型")',
        '[class*="addSKUName"]:has-text("创建类型")',
        '[class*="popupFooter"]:has-text("创建类型")',
    ]
    for selector in playwright_selectors:
        locator = page.locator(selector).last
        if locator.count() == 0:
            continue
        try:
            locator.scroll_into_view_if_needed(timeout=2_000)
            locator.click(timeout=3_000, force=True)
            time.sleep(0.35)
            if _wait_for_create_type_input(page):
                return True
        except Exception:
            continue

    clicked = bool(
        page.evaluate(
            """
            () => {
              function visible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              function clickCreateType(el) {
                const inner = Array.from(el.querySelectorAll('span, a, button')).find((node) => {
                  const t = (node.innerText || node.textContent || '').trim();
                  return t === '创建类型' && visible(node);
                });
                const target = inner || el;
                try {
                  target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                  target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                  target.click();
                  return true;
                } catch (e) {
                  return false;
                }
              }
              const prioritySelectors = [
                '[class*="newSKU"]',
                '[class*="addSKUName"]',
                '[class*="popupFooter"]',
              ];
              for (const sel of prioritySelectors) {
                for (const el of document.querySelectorAll(sel)) {
                  const t = (el.innerText || el.textContent || '').trim();
                  if (!t.includes('创建类型')) continue;
                  if (!visible(el)) continue;
                  if (clickCreateType(el)) return true;
                }
              }
              for (const el of document.querySelectorAll('span, a, button')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (t !== '创建类型') continue;
                if (!visible(el)) continue;
                if (clickCreateType(el)) return true;
              }
              return false;
            }
            """
        )
    )
    if not clicked:
        return False
    time.sleep(0.35)
    return _wait_for_create_type_input(page)


def _wait_for_create_type_input(page: Page, *, max_wait: float = 5.0) -> bool:
    """点击「创建类型」后等待底部规格值输入框出现。"""
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            if page.locator('input[placeholder*="请输入规格值"]').count() > 0:
                return True
        except Exception:
            pass
        visible = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('input')).some((inp) => {
              const ph = (inp.getAttribute('placeholder') || '').trim();
              if (!ph.includes('请输入规格值')) return false;
              const r = inp.getBoundingClientRect();
              const s = getComputedStyle(inp);
              return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            })
            """
        )
        if visible:
            return True
        time.sleep(0.2)
    return False


def _click_color_family_tab(page: Page, family: str) -> bool:
    """切换颜色分类左侧色系 Tab（如 褐色系）。"""
    return bool(
        page.evaluate(
            """
            (family) => {
              function visible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              for (const el of document.querySelectorAll('li, div, span')) {
                const t = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
                if (t !== family && !t.startsWith(family)) continue;
                if (!visible(el)) continue;
                try {
                  el.click();
                  return true;
                } catch (e) {}
              }
              return false;
            }
            """,
            family,
        )
    )


def _try_select_color_in_families(page: Page, candidates: list[str]) -> str:
    """在颜色分类各色系中查找并勾选已有颜色（如 褐色系 → 卡其色）。"""
    picked = _click_option_in_open_popup(page, candidates)
    if picked:
        return picked
    for family in COLOR_FAMILY_TABS:
        if not _click_color_family_tab(page, family):
            continue
        time.sleep(0.35)
        picked = _click_option_in_open_popup(page, candidates)
        if picked:
            return picked
    return ""


def _click_option_in_open_popup(page: Page, candidates: list[str]) -> str:
    """在下拉弹层中点击与候选值精确匹配的选项，返回命中的值。"""
    if not candidates:
        return ""
    return str(
        page.evaluate(
            """
            (candidates) => {
              function visible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              const roots = [];
              for (const sel of [
                '.ecom-g-cascader-menus',
                '[class*="cascader-menu"]',
                '[class*="CascaderMenu"]',
                '[class*="popup"]',
                '[class*="Popup"]',
                '[class*="dropdown"]',
              ]) {
                for (const el of document.querySelectorAll(sel)) {
                  if (visible(el)) roots.push(el);
                }
              }
              if (!roots.length) roots.push(document.body);
              for (const root of roots) {
                for (const el of root.querySelectorAll('label, li, span, div')) {
                  const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                  if (!t || t.length > 40) continue;
                  if (!visible(el)) continue;
                  if (!candidates.includes(t)) continue;
                  const label = el.closest('label') || (el.tagName === 'LABEL' ? el : null);
                  const row = label || el.closest('li, [class*="checkbox"], [class*="Checkbox"]') || el;
                  try {
                    const checkbox = row.querySelector('input[type="checkbox"]');
                    (checkbox || row).click();
                    return t;
                  } catch (e) {}
                }
              }
              return '';
            }
            """,
            candidates,
        )
    ).strip()


def _try_select_existing_and_confirm(page: Page, value: str, *, dimension_label: str = "") -> str:
    """优先勾选下拉已有规格项（如 卡其色），避免不必要的「创建类型」。"""
    candidates = _spec_value_candidates(value)
    if dimension_label == COLOR_DIMENSION:
        picked = _try_select_color_in_families(page, candidates)
        if picked and _click_popup_confirm_button(page):
            return picked
        return ""

    for candidate in candidates:
        picked = _click_option_in_open_popup(page, [candidate])
        if not picked:
            continue
        time.sleep(0.3)
        if _click_popup_confirm_button(page):
            return picked
    return ""


def _fill_create_type_input(page: Page, value: str) -> bool:
    """在下拉底部「请输入规格值」输入框填入规格名。"""
    text = str(value or "").strip()
    if not text:
        return False

    if not _wait_for_create_type_input(page):
        return False

    footer_selectors = [
        '[class*="popupFooter"] input[placeholder*="请输入规格值"]',
        '[class*="PopupFooter"] input[placeholder*="请输入规格值"]',
        'input[placeholder*="请输入规格值"]',
    ]
    for selector in footer_selectors:
        locator = page.locator(selector).last
        if locator.count() == 0:
            continue
        try:
            locator.scroll_into_view_if_needed(timeout=2_000)
            locator.click(timeout=2_000)
            locator.fill(text)
            return True
        except Exception:
            continue

    return bool(
        page.evaluate(
            """
            (val) => {
              function visible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              const inputs = Array.from(document.querySelectorAll('input')).filter((el) => {
                const ph = (el.getAttribute('placeholder') || '').trim();
                return ph.includes('请输入规格值') && visible(el);
              });
              const target = inputs[inputs.length - 1];
              if (!target) return false;
              try { target.focus(); target.click(); } catch (e) {}
              const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
              )?.set;
              if (setter) setter.call(target, val);
              else target.value = val;
              target.dispatchEvent(new InputEvent('input', {
                bubbles: true, data: val, inputType: 'insertText'
              }));
              target.dispatchEvent(new Event('change', { bubbles: true }));
              return (target.value || '').trim() === val;
            }
            """,
            text,
        )
    )


def _click_create_type_checkmark(page: Page) -> bool:
    """点击输入框右侧的勾（data-kora=确认 / success 图标）。"""
    return bool(
        page.evaluate(
            """
            () => {
              function visible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              const selectors = [
                '[data-kora="确认"]',
                '.icon-parcel-success',
                '[class*="icon-parcel-success"]',
                '[class*="success"] svg',
              ];
              for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                  const clickTarget = el.tagName === 'svg' ? (el.closest('span, button') || el) : el;
                  if (visible(clickTarget)) {
                    clickTarget.click();
                    return true;
                  }
                }
              }
              const footers = document.querySelectorAll('[class*="popupFooter"], [class*="PopupFooter"]');
              for (const footer of footers) {
                if (!visible(footer)) continue;
                const input = footer.querySelector('input[placeholder*="请输入规格值"]');
                if (!input) continue;
                const siblings = footer.querySelectorAll('span, button, svg');
                for (const sib of siblings) {
                  if (!visible(sib)) continue;
                  const cls = (sib.className || '').toString();
                  const kora = sib.getAttribute && sib.getAttribute('data-kora');
                  if (kora === '确认' || cls.includes('success')) {
                    (sib.closest('span, button') || sib).click();
                    return true;
                  }
                }
              }
              return false;
            }
            """
        )
    )


def _wait_create_type_value_ready(page: Page, value: str, *, max_wait: int = 15) -> bool:
    """等待勾选对勾后：自定义列表出现该值且「确定」按钮可点。"""
    candidates = _spec_value_candidates(value)
    for _ in range(max_wait):
        ready = page.evaluate(
            """
            (candidates) => {
              function visible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              let valueReady = false;
              for (const el of document.querySelectorAll('*')) {
                const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                if (!candidates.includes(t)) continue;
                const parent = el.closest('[class*="cascader"], [class*="popup"], [class*="menu"]');
                if (parent && visible(el)) {
                  valueReady = true;
                  break;
                }
              }
              let confirmReady = false;
              for (const btn of document.querySelectorAll('button')) {
                if (!visible(btn) || btn.disabled) continue;
                const t = (btn.innerText || btn.textContent || '').trim();
                if (t.startsWith('确定')) {
                  confirmReady = true;
                  break;
                }
              }
              return valueReady && confirmReady;
            }
            """,
            candidates,
        )
        if ready:
            return True
        time.sleep(0.3)
    return False


def _click_popup_confirm_button(page: Page) -> bool:
    """点击下拉底部蓝色「确定」按钮。"""
    return bool(
        page.evaluate(
            """
            () => {
              function visible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              const footers = document.querySelectorAll('[class*="popupFooter"], [class*="PopupFooter"]');
              for (const footer of footers) {
                if (!visible(footer)) continue;
                for (const btn of footer.querySelectorAll('button')) {
                  if (!visible(btn) || btn.disabled) continue;
                  const t = (btn.innerText || btn.textContent || '').trim();
                  if (t.startsWith('确定')) {
                    btn.click();
                    return true;
                  }
                }
              }
              for (const btn of document.querySelectorAll('button.ecom-g-btn-primary, button[class*="btn-primary"]')) {
                if (!visible(btn) || btn.disabled) continue;
                const t = (btn.innerText || btn.textContent || '').trim();
                if (t.startsWith('确定')) {
                  btn.click();
                  return true;
                }
              }
              return false;
            }
            """
        )
    )


def _fill_and_confirm_create_type_value(page: Page, value: str) -> tuple[bool, str]:
    """
    创建类型完整流程：
    1. 在「请输入规格值」输入框填值
    2. 点右侧勾
    3. 等待自定义列表勾选
    4. 点底部「确定」
  返回 (成功与否, 失败原因)。
    """
    if not _fill_create_type_input(page, value):
        return False, "填写规格值失败"
    time.sleep(0.2)
    if not _click_create_type_checkmark(page):
        try:
            page.keyboard.press("Enter")
        except Exception:
            return False, "点击确认勾失败"
    time.sleep(CONFIRM_CHECK_WAIT_SECONDS)
    if not _wait_create_type_value_ready(page, value):
        return False, "规格值未出现在列表或确定按钮不可用"
    time.sleep(0.2)
    if not _click_popup_confirm_button(page):
        return False, "点击确定失败"
    return True, ""


def _wait_dimension_visible(page: Page, dimension_label: str, *, max_wait: int = 20) -> bool:
    for sec in range(max_wait):
        visible = page.evaluate(
            """
            (dimensionLabel) => {
              for (const el of document.querySelectorAll('*')) {
                const t = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
                if (t === dimensionLabel || t.startsWith(dimensionLabel)) return true;
              }
              return false;
            }
            """,
            dimension_label,
        )
        if visible:
            return True
        time.sleep(0.5)
    return False


def _count_pickers_in_block(page: Page, dimension_label: str) -> int:
    handle = _find_dimension_block_root(page, dimension_label)
    if not handle:
        return 0
    try:
        return int(
            page.evaluate(
                """
                (root) => {
                  if (!root) return 0;
                  return root.querySelectorAll(
                    '.ecom-g-cascader-picker, [class*="cascader-picker"]'
                  ).length;
                }
                """,
                handle,
            )
            or 0
        )
    finally:
        try:
            handle.dispose()
        except Exception:
            pass


def _count_picker_tags(page: Page, dimension_label: str) -> int:
    handle = _find_spec_section_root(page, dimension_label)
    if not handle:
        return 0
    try:
        return int(
            page.evaluate(
                """
                (root) => {
                  if (!root) return 0;
                  const tags = root.querySelectorAll(
                    '.ecom-g-cascader-selection-item, .ant-select-selection-item, [class*="tag"], [class*="Tag"]'
                  );
                  return tags.length;
                }
                """,
                handle,
            )
            or 0
        )
    finally:
        try:
            handle.dispose()
        except Exception:
            pass


def _add_one_spec_value_via_cascader(
    page: Page,
    account_id: str,
    listing_label: str,
    dimension_label: str,
    value: str,
    *,
    index: int,
    total: int,
) -> None:
    """级联下拉 + 创建类型流程（兜底）。"""
    before_tags = _count_picker_tags(page, dimension_label)

    if index > 0:
        if not _wait_for_spec_value_slot(page, dimension_label, index):
            _log(account_id, listing_label, f"等待「{dimension_label}」第 {index + 1} 个输入槽…")
        time.sleep(0.35)

    if not _open_rightmost_empty_slot_dropdown(page, dimension_label):
        raise RuntimeError(f"未找到「{dimension_label}」规格下拉框")

    time.sleep(0.6)
    if not _click_create_type_in_popup(page):
        raise RuntimeError(f"未找到「{dimension_label}」下拉中的「{CREATE_TYPE_TEXT}」按钮")

    _log(account_id, listing_label, f"已点击「{CREATE_TYPE_TEXT}」，准备填写：{value}")
    last_reason = ""
    applied = ""
    for candidate in _spec_value_candidates(value):
        ok, reason = _fill_and_confirm_create_type_value(page, candidate)
        if ok:
            applied = candidate
            break
        last_reason = reason
        if candidate != _spec_value_candidates(value)[-1]:
            _log(account_id, listing_label, f"创建类型尝试「{candidate}」失败：{reason}，换候选重试…")
            if not _click_create_type_in_popup(page):
                last_reason = "重新点击创建类型失败"
                break

    if not applied:
        detail = f"（{last_reason}）" if last_reason else ""
        raise RuntimeError(f"「{dimension_label}」创建类型确认失败: {value}{detail}")

    time.sleep(0.6)
    after_tags = _count_picker_tags(page, dimension_label)
    _log(
        account_id,
        listing_label,
        f"已录入{dimension_label} ({index + 1}/{total})：{applied}（tags {before_tags}→{after_tags}）",
    )
    if index >= 2:
        time.sleep(0.5)


def _add_one_spec_value(
    page: Page,
    account_id: str,
    listing_label: str,
    dimension_label: str,
    value: str,
    *,
    index: int,
    total: int,
    prefer_inline: bool,
) -> None:
    _scroll_spec_section(page)
    if _react_fill_inline_spec_in_block(page, dimension_label, value, index=index):
        _log(
            account_id,
            listing_label,
            f"已录入{dimension_label} ({index + 1}/{total})：{value}（手动输入）",
        )
        time.sleep(0.5 if index < 2 else 0.9)
        return
    _add_one_spec_value_via_cascader(
        page,
        account_id,
        listing_label,
        dimension_label,
        value,
        index=index,
        total=total,
    )


def _add_one_spec_value_via_create_type(
    page: Page,
    account_id: str,
    listing_label: str,
    dimension_label: str,
    value: str,
    *,
    index: int,
    total: int,
) -> None:
    """兼容旧调用：默认走级联创建类型。"""
    _add_one_spec_value_via_cascader(
        page,
        account_id,
        listing_label,
        dimension_label,
        value,
        index=index,
        total=total,
    )


def fill_spec_dimensions_via_create_type(
    page: Page,
    account_id: str,
    listing_label: str,
    style_names: list[str],
    size_names: list[str],
) -> dict:
    """
    抖店规格填表（对齐拼多多）：
    - 第 1 维 颜色分类 ← ordered_style_names（AI 识色）
    - 第 2 维 尺寸大小 ← unit.model_codes（笔袋+挂件 等）
    """
    _scroll_spec_section(page)
    if not _wait_dimension_visible(page, COLOR_DIMENSION):
        raise RuntimeError("未找到「颜色分类」规格区域")

    color_values = [str(n).strip() for n in style_names if str(n).strip()]
    size_values = [str(n).strip() for n in size_names if str(n).strip()]
    prefer_inline = _is_manual_inline_spec_ui(page)
    _log(
        account_id,
        listing_label,
        f"规格填表：颜色分类={color_values}；尺寸大小={size_values}；"
        f"UI={'手动输入' if prefer_inline else '级联下拉'}",
    )

    for idx, name in enumerate(color_values):
        _add_one_spec_value(
            page,
            account_id,
            listing_label,
            COLOR_DIMENSION,
            name,
            index=idx,
            total=len(color_values),
            prefer_inline=prefer_inline,
        )

    if size_values:
        if not _wait_dimension_visible(page, SIZE_DIMENSION, max_wait=15):
            _log(account_id, listing_label, "录入颜色后未立即出现「尺寸大小」，继续尝试…")
        time.sleep(0.5)
        for idx, name in enumerate(size_values):
            _add_one_spec_value(
                page,
                account_id,
                listing_label,
                SIZE_DIMENSION,
                name,
                index=idx,
                total=len(size_values),
                prefer_inline=prefer_inline,
            )

    sku_rows = _wait_sku_table_rows(page, account_id, listing_label, expected=len(color_values) * len(size_values))

    return {
        "color_values": color_values,
        "size_values": size_values,
        "sku_rows_visible": sku_rows,
    }


def _wait_sku_table_rows(
    page: Page,
    account_id: str,
    listing_label: str,
    *,
    expected: int,
    max_wait: int = 30,
) -> int:
    """等待价格与库存区出现带输入框的 SKU 明细行（勿把表头/其它表误判为就绪）。"""
    target = max(1, expected)
    count = 0
    for sec in range(max_wait):
        count = page.evaluate(
            """
            () => {
              function norm(t) {
                return String(t || '').replace(/\\s+/g, ' ').trim();
              }
              function isBatch(tr) {
                const t = norm(tr.innerText || '');
                return t.includes('批量设置') || t.includes('全部颜色') || t.includes('全部尺寸');
              }
              function editable(inp) {
                if (!inp || inp.disabled) return false;
                const ty = String(inp.getAttribute('type') || inp.type || 'text').toLowerCase();
                return !['file','hidden','checkbox','radio','button','submit'].includes(ty);
              }
              function inputCount(tr) {
                return Array.from(tr.querySelectorAll('input')).filter(editable).length;
              }
              const root = Array.from(document.querySelectorAll('div, section')).find((el) => {
                const t = norm(el.innerText || '').slice(0, 4000);
                return t.includes('价格与库存') && (t.includes('现货库存') || t.includes('商家编码'));
              }) || document.body;
              let best = 0;
              for (const tr of root.querySelectorAll('tr')) {
                if (isBatch(tr)) continue;
                if (inputCount(tr) >= 2) best += 1;
              }
              return best;
            }
            """
        )
        count = int(count or 0)
        if count >= target:
            _log(account_id, listing_label, f"SKU 价格表明细行就绪: {count}")
            return count
        if sec == 0 or (sec + 1) % 5 == 0:
            _log(account_id, listing_label, f"等待 SKU 价格表明细行… ({count}/{target}) ({sec + 1}/{max_wait}s)")
        time.sleep(1)
    _log(account_id, listing_label, f"SKU 价格表明细行超时: {count}/{target}（将在 Step5 再等）")
    return int(count or 0)

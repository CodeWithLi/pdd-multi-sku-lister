"""抖店发布页「基础信息 → 类目属性」：品牌（搜索下拉）+ 生产企业名称（文本）。"""

from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import Page


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _click_basic_info_tab(page: Page) -> bool:
    selectors = [
        "div[role='tab']:has-text('基础信息')",
        "div.ecom-g-tabs-tab:has-text('基础信息')",
        "[class*='tabs-tab']:has-text('基础信息')",
    ]
    for selector in selectors:
        tab = page.locator(selector)
        if tab.count() <= 0:
            continue
        try:
            tab.first.click(timeout=4_000)
            time.sleep(0.6)
            return True
        except Exception:
            continue
    try:
        page.get_by_text("基础信息", exact=True).first.click(timeout=4_000)
        time.sleep(0.6)
        return True
    except Exception:
        return False


def _scroll_to_category_attrs(page: Page) -> None:
    try:
        page.evaluate(
            """
            () => {
              const markers = ['类目属性', '必填项完成度', '* 品牌', '生产企业名称'];
              for (const marker of markers) {
                const nodes = Array.from(document.querySelectorAll('div, section, span, label, h3, h4'));
                const hit = nodes.find((el) => {
                  const t = (el.innerText || '').trim();
                  return t.includes(marker) && t.length < 80;
                });
                if (hit) {
                  try { hit.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
                  return true;
                }
              }
              return false;
            }
            """
        )
    except Exception:
        pass
    time.sleep(0.35)


def _find_attr_input(page: Page, label: str) -> Any:
    """按标签文案定位相邻输入框（品牌 / 生产企业名称）。"""
    handle = page.evaluate_handle(
        """
        (label) => {
          function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
          }
          const norm = (t) => String(t || '').replace(/\\s+/g, ' ').trim();
          const labelNorm = norm(label).replace(/^\\*/, '');
          const nodes = Array.from(document.querySelectorAll('div, label, span, p'));
          const scored = [];
          for (const node of nodes) {
            const raw = norm(node.innerText || node.textContent || '');
            if (!raw || raw.length > 40) continue;
            const compact = raw.replace(/^\\*\\s*/, '');
            let score = 0;
            if (compact === labelNorm || compact === ('*' + labelNorm) || raw === ('* ' + labelNorm)) score = 100;
            else if (compact.endsWith(labelNorm) && compact.length <= labelNorm.length + 4) score = 80;
            else if (compact.includes(labelNorm) && compact.length <= labelNorm.length + 8) score = 40;
            else continue;
            // 避开下拉选项文案本身
            if (raw === '无品牌' || raw.includes('新增品牌')) continue;
            let root = node;
            for (let i = 0; i < 8 && root; i++) {
              const inputs = Array.from(root.querySelectorAll(
                'input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file])'
              )).filter(visible);
              if (inputs.length) {
                scored.push({ score: score - i, input: inputs[0] });
                break;
              }
              root = root.parentElement;
            }
          }
          scored.sort((a, b) => b.score - a.score);
          return scored.length ? scored[0].input : null;
        }
        """,
        label,
    )
    element = handle.as_element()
    if element:
        return element

    # Playwright 兜底
    try:
        loc = page.locator(
            f"xpath=//*[contains(normalize-space(.), '{label}') and string-length(normalize-space(.)) < 40]"
            f"/ancestor::div[position()<=6]"
            f"//input[not(@type='hidden') and not(@type='checkbox') and not(@type='file')]"
        )
        if loc.count() > 0 and loc.first.is_visible(timeout=800):
            return loc.first
    except Exception:
        pass
    return None


def _react_fill_input(page: Page, input_el: Any, value: str) -> bool:
    try:
        input_el.click(timeout=3_000)
        time.sleep(0.15)
        try:
            input_el.fill("")
        except Exception:
            pass
        input_el.fill(value, timeout=3_000)
        time.sleep(0.2)
        return True
    except Exception:
        # ElementHandle / Locator 都试 JS 写入
        try:
            return bool(
                page.evaluate(
                    """
                    ([el, val]) => {
                      if (!el) return false;
                      el.focus();
                      const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                      )?.set;
                      if (setter) setter.call(el, val);
                      else el.value = val;
                      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: val, inputType: 'insertText' }));
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                      return true;
                    }
                    """,
                    [input_el, value],
                )
            )
        except Exception:
            return False


def _select_first_dropdown_option(page: Page, preferred: str = "无品牌") -> bool:
    preferred = (preferred or "").strip()
    selectors = [
        ".ecom-g-select-dropdown:not(.ecom-g-select-dropdown-hidden) .ecom-g-select-item-option-content",
        ".ecom-g-select-dropdown:not(.ecom-g-select-dropdown-hidden) .ecom-g-select-item-option",
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content",
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
        ".ecom-g-select-item-option-content",
        ".ecom-g-select-item-option",
        ".ant-select-item-option-content",
        ".ant-select-item-option",
        '[class*="select-item-option-content"]',
        '[class*="select-item-option"]',
        'div[role="option"]',
        'li[role="option"]',
    ]
    deadline = time.time() + 8
    while time.time() < deadline:
        for selector in selectors:
            opts = page.locator(selector)
            count = opts.count()
            if count <= 0:
                continue
            # 优先精确匹配
            for i in range(min(count, 20)):
                try:
                    text = (opts.nth(i).inner_text(timeout=500) or "").strip()
                except Exception:
                    continue
                if not text or "新增品牌" in text or "申请新品牌" in text or "去申请" in text:
                    continue
                if preferred and (text == preferred or text.startswith(preferred)):
                    try:
                        opts.nth(i).click(timeout=2_000)
                        time.sleep(0.35)
                        return True
                    except Exception:
                        continue
            # 否则点第一个有效项
            for i in range(min(count, 10)):
                try:
                    text = (opts.nth(i).inner_text(timeout=500) or "").strip()
                except Exception:
                    continue
                if not text or "新增品牌" in text or "申请新品牌" in text or "去申请" in text:
                    continue
                try:
                    opts.nth(i).click(timeout=2_000)
                    time.sleep(0.35)
                    return True
                except Exception:
                    continue
        time.sleep(0.25)
    return False


def _find_brand_select_root(page: Page) -> Any:
    """定位「品牌」旁的 ecom-g-select 根节点。"""
    handle = page.evaluate_handle(
        """
        () => {
          function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
          }
          const norm = (t) => String(t || '').replace(/\\s+/g, ' ').trim();
          const nodes = Array.from(document.querySelectorAll('div, label, span, p'));
          for (const node of nodes) {
            const raw = norm(node.innerText || node.textContent || '');
            if (!raw || raw.length > 24) continue;
            const compact = raw.replace(/^\\*\\s*/, '');
            if (compact !== '品牌' && raw !== '* 品牌' && raw !== '*品牌') continue;
            let root = node;
            for (let i = 0; i < 10 && root; i++) {
              const sel = root.querySelector(
                '.ecom-g-select, .ant-select, [class*="ecom-g-select"]'
              );
              if (sel && visible(sel)) return sel;
              const selector = root.querySelector(
                '.ecom-g-select-selector, .ant-select-selector'
              );
              if (selector && visible(selector)) {
                return selector.closest('.ecom-g-select, .ant-select') || selector;
              }
              root = root.parentElement;
            }
          }
          // 回退：类目属性区内第一个带 selection-item 的 select
          const section = Array.from(document.querySelectorAll('div, section')).find((el) => {
            const t = norm(el.innerText || '').slice(0, 800);
            return t.includes('类目属性') && t.includes('品牌') && t.includes('生产企业名称');
          });
          if (section) {
            const sel = section.querySelector('.ecom-g-select, .ant-select');
            if (sel && visible(sel)) return sel;
          }
          return null;
        }
        """
    )
    return handle.as_element()


def _read_brand_selected(page: Page, select_root: Any | None = None) -> str:
    try:
        if select_root is not None:
            text = page.evaluate(
                """
                (root) => {
                  const item = root.querySelector(
                    '.ecom-g-select-selection-item, .ant-select-selection-item'
                  );
                  return item ? (item.getAttribute('title') || item.textContent || '').trim() : '';
                }
                """,
                select_root,
            )
            return str(text or "").strip()
        loc = page.locator(".ecom-g-select-selection-item, .ant-select-selection-item").first
        if loc.count() > 0:
            return (loc.get_attribute("title") or loc.inner_text(timeout=800) or "").strip()
    except Exception:
        pass
    return ""


def _click_brand_select(page: Page, select_root: Any) -> bool:
    try:
        clicked = page.evaluate(
            """
            (root) => {
              const selector = root.querySelector(
                '.ecom-g-select-selector, .ant-select-selector'
              ) || root;
              selector.click();
              return true;
            }
            """,
            select_root,
        )
        time.sleep(0.35)
        return bool(clicked)
    except Exception:
        try:
            page.locator(".ecom-g-select-selector, .ant-select-selector").first.click(timeout=3_000)
            time.sleep(0.35)
            return True
        except Exception:
            return False


def _type_into_brand_search(page: Page, brand: str) -> bool:
    """下拉打开后，向搜索框输入品牌名。"""
    search_selectors = [
        ".ecom-g-select-selection-search-input",
        ".ant-select-selection-search-input",
        "input.ecom-g-select-selection-search-input",
        ".ecom-g-select-focused input",
        ".ant-select-focused input",
        ".ecom-g-select-open input:not([type=hidden])",
        ".ant-select-open input:not([type=hidden])",
        ".ecom-g-select-dropdown input",
        ".ant-select-dropdown input",
        "input[role='combobox']",
    ]
    for selector in search_selectors:
        loc = page.locator(selector)
        try:
            count = loc.count()
        except Exception:
            continue
        for i in range(min(count, 6)):
            item = loc.nth(i)
            try:
                if not item.is_visible(timeout=400):
                    continue
                item.click(timeout=1_500)
                item.fill("")
                item.fill(brand, timeout=2_000)
                time.sleep(0.35)
                return True
            except Exception:
                continue

    # keyboard 兜底：焦点已在 select 上
    try:
        page.keyboard.type(brand, delay=40)
        time.sleep(0.35)
        return True
    except Exception:
        return False


def fill_brand_dropdown(
    page: Page,
    account_id: str,
    listing_label: str,
    *,
    brand: str = "无品牌",
) -> dict[str, Any]:
    brand = (brand or "无品牌").strip() or "无品牌"
    _log(account_id, listing_label, f"类目属性：填写品牌「{brand}」…")

    # 类目属性常在选类目后异步渲染
    select_root = None
    for _ in range(20):
        select_root = _find_brand_select_root(page)
        if select_root is not None:
            break
        time.sleep(0.4)
    if select_root is None:
        raise RuntimeError(f"[{account_id}] [{listing_label}] 未找到「品牌」下拉框（ecom-g-select）")

    try:
        select_root.scroll_into_view_if_needed(timeout=3_000)
    except Exception:
        pass

    current = _read_brand_selected(page, select_root)
    if current == brand:
        _log(account_id, listing_label, f"类目属性：品牌已是「{brand}」，跳过重选")
        return {"brand": brand, "ok": True, "skipped": True}

    if not _click_brand_select(page, select_root):
        raise RuntimeError(f"[{account_id}] [{listing_label}] 点击品牌下拉失败")

    if not _type_into_brand_search(page, brand):
        raise RuntimeError(f"[{account_id}] [{listing_label}] 品牌搜索框输入失败")

    time.sleep(0.45)
    if not _select_first_dropdown_option(page, preferred=brand):
        try:
            page.keyboard.press("Enter")
            time.sleep(0.3)
        except Exception:
            pass
        if not _select_first_dropdown_option(page, preferred=brand):
            # 再次核对是否已显示目标值（有的类目默认就是无品牌）
            again = _read_brand_selected(page, select_root)
            if again != brand:
                raise RuntimeError(f"[{account_id}] [{listing_label}] 品牌下拉未选中「{brand}」")

    final = _read_brand_selected(page, select_root) or brand
    _log(account_id, listing_label, f"类目属性：品牌已选「{final}」")
    return {"brand": final, "ok": True}



def fill_manufacturer_name(
    page: Page,
    account_id: str,
    listing_label: str,
    *,
    manufacturer_name: str,
) -> dict[str, Any]:
    value = (manufacturer_name or "").strip()
    if not value:
        raise RuntimeError(
            f"[{account_id}] [{listing_label}] 未配置「生产企业名称」，请在上架页填写后再试"
        )

    _log(account_id, listing_label, f"类目属性：填写生产企业名称「{value}」…")
    # 必填文本框标签（笔袋类目）
    inp = _find_attr_input(page, "生产企业名称")
    if inp is None:
        # 少数类目文案差异
        for alt in ("生产厂家", "厂家名称", "制造商"):
            inp = _find_attr_input(page, alt)
            if inp is not None:
                break
    if inp is None:
        raise RuntimeError(f"[{account_id}] [{listing_label}] 未找到「生产企业名称」输入框")

    try:
        inp.scroll_into_view_if_needed(timeout=3_000)
    except Exception:
        pass
    if not _react_fill_input(page, inp, value):
        raise RuntimeError(f"[{account_id}] [{listing_label}] 生产企业名称填写失败")

    # 失焦触发校验
    try:
        inp.press("Tab")
    except Exception:
        try:
            page.keyboard.press("Tab")
        except Exception:
            pass

    _log(account_id, listing_label, f"类目属性：生产企业名称已填「{value}」")
    return {"manufacturer_name": value, "ok": True}


def fill_category_attributes(
    page: Page,
    account_id: str,
    listing_label: str,
    *,
    brand: str = "无品牌",
    manufacturer_name: str = "",
) -> dict[str, Any]:
    """填写基础信息页必填类目属性：品牌下拉 + 生产企业名称文本。

    注意：该类目属性区通常在点击「下一步」之后才渲染，请在下一步成功后再调用。
    """
    _click_basic_info_tab(page)
    time.sleep(0.5)
    _scroll_to_category_attrs(page)

    # 等类目属性区渲染（下一步后的基础信息页）
    for sec in range(30):
        ready = page.evaluate(
            """
            () => {
              const t = (document.body && document.body.innerText) || '';
              const hasAttrs = t.includes('类目属性') || t.includes('必填项完成度');
              const hasBrand = t.includes('品牌');
              const hasMfr = t.includes('生产企业名称') || t.includes('生产厂家') || t.includes('制造商');
              return hasAttrs && hasBrand && hasMfr;
            }
            """
        )
        if ready:
            break
        # 有时停在图文信息 Tab，再点一次基础信息
        if sec in (3, 8, 15):
            _click_basic_info_tab(page)
            _scroll_to_category_attrs(page)
        if sec == 0 or (sec + 1) % 5 == 0:
            _log(account_id, listing_label, f"等待类目属性区… ({sec + 1}/30s)")
        time.sleep(1)
    else:
        raise RuntimeError(
            f"[{account_id}] [{listing_label}] 类目属性区未出现"
            f"（应在「下一步」后的基础信息页；当前可能仍在图文信息或其他 Tab）"
        )

    _scroll_to_category_attrs(page)
    brand_result = fill_brand_dropdown(
        page, account_id, listing_label, brand=brand or "无品牌"
    )
    time.sleep(0.35)
    mfr_result = fill_manufacturer_name(
        page, account_id, listing_label, manufacturer_name=manufacturer_name
    )
    return {
        "category_attrs_ok": True,
        "brand": brand_result.get("brand"),
        "manufacturer_name": mfr_result.get("manufacturer_name"),
    }

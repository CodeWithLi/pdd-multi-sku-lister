"""发布页第三步：价格库存 → 切换手动填写。"""

from __future__ import annotations

import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _page_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return ""


def is_manual_spec_page(page: Page) -> bool:
    """是否已进入手动规格/价格库存填写页。"""
    text = _page_text(page)
    if "价格与库存" not in text:
        return False
    manual_markers = ("颜色分类", "尺寸大小", "规格批量模板")
    return any(marker in text for marker in manual_markers)


def is_ai_assistant_spec_page(page: Page) -> bool:
    text = _page_text(page)
    return "AI 智能填写助手" in text or "切换手动填写" in text


def click_price_stock_tab(page: Page, account_id: str, label: str) -> bool:
    """点击顶部「价格库存」标签。"""
    _log(account_id, label, "切换到「价格库存」标签…")
    selectors = [
        "div[role='tab']:has-text('价格库存')",
        "div.ecom-g-tabs-tab:has-text('价格库存')",
        "[class*='tabs-tab']:has-text('价格库存')",
    ]
    for selector in selectors:
        tab = page.locator(selector)
        if tab.count() > 0:
            try:
                tab.first.click(timeout=5_000)
                time.sleep(1)
                return True
            except Exception:
                continue
    try:
        page.get_by_text("价格库存", exact=True).first.click(timeout=5_000)
        time.sleep(1)
        return True
    except PlaywrightTimeoutError:
        return False
    except Exception:
        return False


def _click_switch_to_manual_button(page: Page) -> bool:
    """点击「切换手动填写」。"""
    candidates = [
        page.locator("button[class*='switchButton']").filter(has_text="切换手动填写"),
        page.locator("div[class*='manualUploadEntry']").filter(has_text="切换手动填写"),
        page.locator("[data-testid='sku-info-assistant']").get_by_text("切换手动填写", exact=True),
        page.get_by_text("切换手动填写", exact=True),
    ]
    for locator in candidates:
        if locator.count() <= 0:
            continue
        try:
            locator.first.scroll_into_view_if_needed(timeout=3_000)
            locator.first.click(timeout=5_000)
            return True
        except Exception:
            continue

    try:
        clicked = page.evaluate(
            """
            () => {
              function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              const nodes = Array.from(document.querySelectorAll('button, span, div, a'));
              const target = nodes.find((el) => {
                if (!isVisible(el)) return false;
                const t = (el.innerText || '').trim();
                return t === '切换手动填写' || t.includes('切换手动填写');
              });
              if (!target) return false;
              target.click();
              return true;
            }
            """
        )
        return bool(clicked)
    except Exception:
        return False


def wait_for_manual_spec_page(page: Page, account_id: str, label: str, *, max_wait: int = 30) -> bool:
    for sec in range(max_wait):
        if is_manual_spec_page(page):
            _log(account_id, label, "已进入手动规格填写页（颜色分类/价格与库存）")
            return True
        if sec == 0 or (sec + 1) % 5 == 0:
            _log(account_id, label, f"等待手动规格页… ({sec + 1}/{max_wait}s)")
        time.sleep(1)
    return False


def switch_to_manual_price_stock(
    page: Page,
    account_id: str,
    label: str,
) -> dict:
    """
    价格库存第三步：
    1. 点击「价格库存」标签
    2. 点击「切换手动填写」
    3. 等待手动规格页出现
    """
    if is_manual_spec_page(page):
        _log(account_id, label, "已在手动规格填写页，跳过切换")
        return {"price_stock_tab_clicked": False, "manual_switch_clicked": False, "already_manual": True}

    if not click_price_stock_tab(page, account_id, label):
        raise RuntimeError(f"[{account_id}] [{label}] 未找到「价格库存」标签")

    time.sleep(1)
    if is_manual_spec_page(page):
        _log(account_id, label, "价格库存标签已是手动填写模式")
        return {"price_stock_tab_clicked": True, "manual_switch_clicked": False, "already_manual": True}

    if not is_ai_assistant_spec_page(page):
        _log(account_id, label, "未检测到 AI 助手页，尝试直接点击「切换手动填写」")

    _scroll_spec_section(page)
    if not _click_switch_to_manual_button(page):
        raise RuntimeError(f"[{account_id}] [{label}] 未找到「切换手动填写」按钮")

    _log(account_id, label, "已点击「切换手动填写」")
    time.sleep(1)

    if not wait_for_manual_spec_page(page, account_id, label):
        raise RuntimeError(f"[{account_id}] [{label}] 切换手动填写后未进入规格页")

    return {
        "price_stock_tab_clicked": True,
        "manual_switch_clicked": True,
        "already_manual": False,
    }


def _scroll_spec_section(page: Page) -> None:
    try:
        page.evaluate(
            """
            () => {
              const nodes = Array.from(document.querySelectorAll('*'));
              const target = nodes.find((el) => {
                const t = (el.innerText || '').trim();
                return t.includes('规格设置') || t.includes('切换手动填写');
              });
              if (target) target.scrollIntoView({ block: 'center', behavior: 'instant' });
            }
            """
        )
    except Exception:
        pass
    time.sleep(0.4)

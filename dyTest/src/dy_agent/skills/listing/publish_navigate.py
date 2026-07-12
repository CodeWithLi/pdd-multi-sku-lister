"""从商家后台进入「商品创建」发布页（新标签页）。"""

from __future__ import annotations

import time

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

GOODS_LIST_URL = "https://fxg.jinritemai.com/ffa/g/list"
CREATE_PRODUCT_HREF = "mcreate"


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _find_create_product_link(page: Page):
    selectors = [
        f'a[href*="{CREATE_PRODUCT_HREF}"]',
        'a[href*="ffa/mcreate"]',
    ]
    for selector in selectors:
        locator = page.locator(selector).filter(has_text="商品创建")
        if locator.count() > 0:
            return locator.first
    return page.get_by_role("link", name="商品创建").first


def ensure_goods_context(page: Page, account_id: str, label: str) -> None:
    """尽量落到商品管理相关页面，便于点击「商品创建」。"""
    text = ""
    try:
        text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        pass

    if "商品创建" in text or "商品管理" in text:
        return

    _log(account_id, label, "当前页无商品创建入口，跳转商品管理…")
    page.goto(GOODS_LIST_URL, wait_until="domcontentloaded")
    time.sleep(2)


def open_publish_page(
    page: Page,
    context: BrowserContext,
    account_id: str,
    label: str,
) -> Page:
    """
    点击「商品创建」打开新标签页，关闭旧标签，返回发布页 Page。
    """
    ensure_goods_context(page, account_id, label)
    link = _find_create_product_link(page)
    link.wait_for(state="visible", timeout=15_000)

    _log(account_id, label, "点击「商品创建」，等待新标签页…")
    try:
        with context.expect_page(timeout=20_000) as new_page_info:
            link.click()
        publish_page = new_page_info.value
    except PlaywrightTimeoutError:
        publish_page = context.pages[-1] if len(context.pages) > 1 else page

    publish_page.wait_for_load_state("domcontentloaded")
    time.sleep(1.5)

    if publish_page != page:
        try:
            page.close()
            _log(account_id, label, "已关闭旧标签页")
        except Exception:
            pass

    publish_page.bring_to_front()
    _log(account_id, label, f"已进入发布页: {publish_page.url}")
    return publish_page

"""抖店发布页：点击「发布商品」→ 等待成功 → 返回商品列表。"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from playwright.sync_api import Page

# 成功页短暂确认即可返回；列表侧靠刷新 + 重试核验，不必空等 20s。
SUBMIT_WAIT_AFTER_SUCCESS_SECONDS = 2


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _page_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5_000)
    except Exception:
        return ""


def _click_publish_product_button(page: Page) -> bool:
    selectors = [
        "button.ecom-g-btn-primary",
        "button:has-text('发布商品')",
    ]
    for selector in selectors:
        btn = page.locator(selector).filter(has_text="发布商品")
        if btn.count() > 0:
            try:
                btn.first.scroll_into_view_if_needed(timeout=5_000)
                btn.first.click(timeout=8_000)
                return True
            except Exception:
                continue
    try:
        page.get_by_role("button", name="发布商品").first.scroll_into_view_if_needed(timeout=5_000)
        page.get_by_role("button", name="发布商品").first.click(timeout=8_000)
        return True
    except Exception:
        return False


def _footer_primary_loading(page: Page) -> bool:
    try:
        loading = page.locator(
            "div[class*='footerBtn'] button.ecom-g-btn-loading, "
            "div[class*='footer'] button.ecom-g-btn-loading"
        )
        if loading.count() > 0 and loading.first.is_visible(timeout=300):
            return True
    except Exception:
        pass
    try:
        loading = page.locator("button.ecom-g-btn-loading").filter(has_text="发布商品")
        if loading.count() > 0 and loading.first.is_visible(timeout=300):
            return True
    except Exception:
        pass
    return False


def _wait_submit_loading(page: Page, *, max_wait: float = 120.0) -> bool:
    deadline = time.time() + max_wait
    seen_loading = False
    while time.time() < deadline:
        if _footer_primary_loading(page):
            seen_loading = True
        elif seen_loading:
            return True
        if _detect_submit_success(page):
            return True
        time.sleep(0.4)
    return _detect_submit_success(page)


def _detect_submit_success(page: Page) -> bool:
    text = _page_text(page)
    markers = ("商品提交成功", "继续发布", "返回商品列表")
    return any(marker in text for marker in markers)


def _wait_submit_success(page: Page, *, max_wait: float = 90.0) -> bool:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if _detect_submit_success(page):
            return True
        time.sleep(0.5)
    return False


def _click_return_goods_list(page: Page) -> bool:
    for label in ("返回商品列表",):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0:
                btn.first.scroll_into_view_if_needed(timeout=5_000)
                btn.first.click(timeout=8_000)
                return True
        except Exception:
            pass
        try:
            btn = page.locator("button.ecom-g-btn").filter(has_text=label)
            if btn.count() > 0:
                btn.first.scroll_into_view_if_needed(timeout=5_000)
                btn.first.click(timeout=8_000)
                return True
        except Exception:
            pass
    return False


def _settle_goods_list_after_return(page: Page, account_id: str, label: str) -> None:
    """返回商品列表后刷新，避免列表尚未就绪导致搜不到刚上架的商品。"""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    time.sleep(1.0)
    _log(account_id, label, "返回商品列表后刷新页面…")
    try:
        page.reload(wait_until="domcontentloaded", timeout=30_000)
    except Exception as exc:
        _log(account_id, label, f"商品列表刷新失败，继续核验: {exc}")
        return
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass
    time.sleep(2.0)


def submit_and_return_goods_list(
    page: Page,
    account_id: str,
    label: str,
    *,
    wait_after_success: int = SUBMIT_WAIT_AFTER_SUCCESS_SECONDS,
) -> dict[str, Any]:
    """点击发布商品，等待成功页，短暂确认后返回商品列表并刷新。"""
    _log(account_id, label, "点击「发布商品」…")
    submitted_at = datetime.now()
    if not _click_publish_product_button(page):
        return {
            "ok": False,
            "reason": "submit_button_missing",
            "submitted_at": submitted_at.isoformat(timespec="seconds"),
        }

    _wait_submit_loading(page, max_wait=120.0)
    success = _wait_submit_success(page, max_wait=90.0)
    if not success:
        _log(account_id, label, "未检测到「商品提交成功」页，仍将尝试返回商品列表核验")
    else:
        _log(account_id, label, "检测到商品提交成功页")

    if wait_after_success > 0:
        _log(account_id, label, f"确认成功后等待 {wait_after_success} 秒，随即返回商品列表…")
        time.sleep(wait_after_success)

    returned = _click_return_goods_list(page)
    if returned:
        _log(account_id, label, "已点击「返回商品列表」")
        _settle_goods_list_after_return(page, account_id, label)
    else:
        _log(account_id, label, "未找到「返回商品列表」，将直接打开商品管理页")

    return {
        "ok": bool(success),
        "success_detected": bool(success),
        "return_clicked": returned,
        "submitted_at": submitted_at.isoformat(timespec="seconds"),
        "wait_after_success": wait_after_success,
        "list_refreshed": bool(returned),
    }

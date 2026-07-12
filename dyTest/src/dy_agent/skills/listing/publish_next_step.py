"""分类页/发布页「下一步」点击（含连点 workaround）。"""

from __future__ import annotations

import random
import time
from typing import Literal

from playwright.sync_api import Page

DEFAULT_BURST_CLICKS = (3, 4, 5)
DEFAULT_ADVANCE_WAIT_BURST = 30
DEFAULT_ADVANCE_WAIT_SIMPLE = 15


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _page_step_token(page: Page) -> str:
    try:
        return str(page.url or "") + "|" + (page.locator("body").inner_text(timeout=2_000)[:200])
    except Exception:
        return str(page.url or "")


def _click_next_button(page: Page) -> bool:
    selectors = [
        "button.ecom-g-btn-primary",
        "button.style_button__QVy4n",
        "button:has-text('下一步')",
    ]
    for selector in selectors:
        button = page.locator(selector).filter(has_text="下一步")
        if button.count() > 0:
            try:
                button.first.click(timeout=5_000)
                return True
            except Exception:
                continue
    try:
        page.get_by_role("button", name="下一步").first.click(timeout=5_000)
        return True
    except Exception:
        return False


def _wait_step_advanced(page: Page, before: str, max_wait: int) -> bool:
    for _ in range(max_wait):
        if _page_step_token(page) != before:
            return True
        time.sleep(1)
    return _page_step_token(page) != before


def click_publish_next_and_advance(
    page: Page,
    account_id: str,
    label: str,
    *,
    burst_demo: bool = True,
) -> tuple[bool, Literal["", "not_found", "no_advance"]]:
    """点击发布页「下一步」；burst_demo 时未跳转则随机连点。"""
    before = _page_step_token(page)
    if not _click_next_button(page):
        return False, "not_found"

    max_wait = DEFAULT_ADVANCE_WAIT_BURST if burst_demo else DEFAULT_ADVANCE_WAIT_SIMPLE
    if _wait_step_advanced(page, before, max_wait=8):
        _log(account_id, label, "已点击「下一步」并检测到页面推进")
        return True, ""

    if not burst_demo:
        return False, "no_advance"

    burst = random.randint(*DEFAULT_BURST_CLICKS)
    _log(account_id, label, f"下一步未推进，开始连点 workaround（{burst} 次）")
    for i in range(burst):
        if not _click_next_button(page):
            break
        time.sleep(0.6)
        if _page_step_token(page) != before:
            _log(account_id, label, f"连点第 {i + 1} 次后页面已推进")
            return True, ""
    if _wait_step_advanced(page, before, max_wait=DEFAULT_ADVANCE_WAIT_BURST):
        return True, ""
    return False, "no_advance"

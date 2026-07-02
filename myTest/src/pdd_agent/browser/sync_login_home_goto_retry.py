"""
同步登录 — 打开首页时的 ERR_ABORTED 重试（可选封装层）。

不改变 ensure_login_sync 其余流程，仅在 dp.get(HOME_URL) 处替换为本函数：
  - 仍使用 wait_until=domcontentloaded（与 DpPage.get 一致）
  - 仅对 net::ERR_ABORTED 重试
  - 若跳转被打断但页面已在拼多多 MMS 域名，视为成功（避免误杀）

回滚：sync_login.py 改回 dp.get(HOME_URL) 即可。
"""

from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import Page

from pdd_agent.browser.safe_navigation import (
    is_acceptable_mms_url,
    is_navigation_aborted_error,
)

DEFAULT_RETRIES = 3
DEFAULT_RETRY_PAUSE_SEC = 1.5


def goto_home_with_aborted_retry(
    page: Page,
    url: str,
    *,
    wait_until: str = "domcontentloaded",
    timeout: int | None = None,
    retries: int = DEFAULT_RETRIES,
    retry_pause_sec: float = DEFAULT_RETRY_PAUSE_SEC,
) -> str:
    """
    打开商家后台首页；ERR_ABORTED 时重试，成功则返回最终 page.url。
    """
    last_exc: BaseException | None = None
    attempts = max(1, int(retries or 1))

    for attempt in range(attempts):
        current_url = str(page.url or "")
        if is_acceptable_mms_url(current_url) and "about:blank" not in current_url:
            return current_url

        try:
            kwargs: dict[str, Any] = {"wait_until": wait_until}
            if timeout is not None:
                kwargs["timeout"] = timeout
            page.goto(url, **kwargs)
            return str(page.url or "")
        except Exception as exc:
            last_exc = exc
            settled_url = str(page.url or "")
            if is_acceptable_mms_url(settled_url):
                return settled_url
            if not is_navigation_aborted_error(exc):
                raise
            if attempt >= attempts - 1:
                raise
            time.sleep(retry_pause_sec)

    if last_exc is not None:
        raise last_exc
    return str(page.url or "")

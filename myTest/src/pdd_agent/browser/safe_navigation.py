"""Playwright 导航容错：处理拼多多首页 goto 时的 net::ERR_ABORTED。"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Page

PDD_MMS_HOST = "mms.pinduoduo.com"
HOME_URL = "https://mms.pinduoduo.com/home/"


def is_navigation_aborted_error(exc: BaseException) -> bool:
    message = str(exc or "").lower()
    return "err_aborted" in message or "net::err_aborted" in message


def is_acceptable_mms_url(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host == PDD_MMS_HOST or host.endswith(f".{PDD_MMS_HOST}")


def safe_goto(
    page: Page,
    url: str,
    *,
    wait_until: str = "domcontentloaded",
    timeout: int | None = None,
    retries: int = 3,
    retry_pause_sec: float = 1.5,
) -> str:
    """
    打开 URL；若 goto 被跳转打断（ERR_ABORTED）但页面已到 MMS，则视为成功。

    返回最终 page.url。
    """
    last_exc: BaseException | None = None
    attempts = max(1, retries)

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
            if not is_navigation_aborted_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(retry_pause_sec)

    if last_exc is not None:
        raise last_exc
    return str(page.url or "")


def safe_goto_home(page: Page, **kwargs: Any) -> str:
    """打开拼多多商家后台首页（带 ERR_ABORTED 容错）。"""
    return safe_goto(page, HOME_URL, **kwargs)

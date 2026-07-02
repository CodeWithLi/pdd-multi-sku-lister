"""浏览器 Context 启动辅助：避免复用恢复中的旧标签页引发导航竞态。"""

from __future__ import annotations

import time

from playwright.sync_api import BrowserContext, Page


def open_task_page(context: BrowserContext, *, settle_sec: float = 0.5) -> Page:
    """
    为自动化任务打开新标签页。

    持久化 Profile 启动时 context.pages[0] 可能仍在恢复上次会话并自动跳转，
    直接对其 goto 容易触发 net::ERR_ABORTED。新标签页共享同一 Cookie，更安全。
    """
    if settle_sec > 0 and context.pages:
        time.sleep(settle_sec)
    return context.new_page()

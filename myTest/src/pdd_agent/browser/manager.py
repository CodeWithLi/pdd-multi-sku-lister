"""Playwright 浏览器生命周期：单 Browser 进程 + 多店铺 Context。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from pdd_agent.core.config import YamlSettings, get_env_settings
from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)


class BrowserManager:
    """按店铺隔离 BrowserContext，共享 Chromium 进程以节省资源。"""

    def __init__(self, settings: YamlSettings) -> None:
        self._settings = settings
        self._env = get_env_settings()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        """启动 Playwright 与 Chromium；headless/slow_mo 优先读 .env。"""
        self._playwright = await async_playwright().start()
        headless = self._env.playwright_headless or self._settings.browser.headless
        slow_mo = self._env.playwright_slow_mo or self._settings.browser.slow_mo
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            slow_mo=slow_mo or None,
        )
        logger.info("Playwright chromium started (headless=%s)", headless)

    async def stop(self) -> None:
        """关闭 Browser 与 Playwright 驱动。"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    @asynccontextmanager
    async def open_context(self, account_id: str) -> AsyncIterator[BrowserContext]:
        """
        为指定店铺打开隔离 Context。
        登录态通过 storage_state 持久化到 data/profiles/{account_id}/state.json。
        """
        if not self._browser:
            raise RuntimeError("BrowserManager not started; call start() first")

        profile_dir = self._settings.paths.resolve("profiles_root") / account_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        state_file = profile_dir / "state.json"
        context = await self._browser.new_context(
            storage_state=str(state_file) if state_file.is_file() else None,
            viewport={"width": 1440, "height": 900},
        )
        context.set_default_timeout(self._settings.browser.default_timeout_ms)
        try:
            yield context
        finally:
            # 退出时写回 Cookie/LocalStorage，下次可免登录
            await context.storage_state(path=str(state_file))
            await context.close()

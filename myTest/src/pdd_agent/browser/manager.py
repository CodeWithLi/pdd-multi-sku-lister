"""Playwright 浏览器生命周期：每店铺独立 Chrome Profile（持久化登录态）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from playwright.async_api import BrowserContext, Playwright, async_playwright

from pdd_agent.browser.stealth import STEALTH_INIT_SCRIPT, STEALTH_LAUNCH_ARGS
from pdd_agent.core.config import YamlSettings, get_env_settings
from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)


class BrowserManager:
    """
    按店铺隔离 Playwright 持久化 Profile（与老项目 ChromeProfiles 完全独立，各跑各的）。

    登录态保存在 data/profiles/{account_id}/user_data/。
    """

    def __init__(self, settings: YamlSettings) -> None:
        self._settings = settings
        self._env = get_env_settings()
        self._playwright: Playwright | None = None

    def _launch_options(self) -> dict[str, Any]:
        headless = self._env.playwright_headless or self._settings.browser.headless
        slow_mo = self._env.playwright_slow_mo or self._settings.browser.slow_mo
        channel = (self._env.playwright_channel or self._settings.browser.channel or "").strip()

        return {
            "headless": headless,
            "slow_mo": slow_mo or None,
            "channel": channel or None,
        }

    async def start(self) -> None:
        """启动 Playwright 驱动（每店铺 Context 在 open_context 时单独拉起）。"""
        self._playwright = await async_playwright().start()
        opts = self._launch_options()
        logger.info(
            "Playwright ready (channel=%s, headless=%s)",
            opts.get("channel") or "bundled-chromium",
            opts.get("headless"),
        )

    async def stop(self) -> None:
        """关闭 Playwright 驱动。"""
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    @asynccontextmanager
    async def open_context(self, account_id: str) -> AsyncIterator[BrowserContext]:
        """
        为指定店铺打开隔离的持久化 Chrome Context。
        比 storage_state 更接近真人：完整 Profile + 禁用自动化标记。
        """
        if not self._playwright:
            raise RuntimeError("BrowserManager not started; call start() first")

        user_data_dir = self._settings.paths.resolve("profiles_root") / account_id / "user_data"
        user_data_dir.mkdir(parents=True, exist_ok=True)

        opts = self._launch_options()
        channel = opts.pop("channel", None)
        slow_mo = opts.pop("slow_mo", None)

        launch_kwargs: dict[str, Any] = {
            "headless": opts["headless"],
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "args": STEALTH_LAUNCH_ARGS,
            "ignore_default_args": ["--enable-automation"],
        }
        if channel:
            launch_kwargs["channel"] = channel
        if slow_mo:
            launch_kwargs["slow_mo"] = slow_mo

        context = await self._playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            **launch_kwargs,
        )
        await context.add_init_script(STEALTH_INIT_SCRIPT)
        context.set_default_timeout(self._settings.browser.default_timeout_ms)
        logger.info("[%s] persistent profile: %s", account_id, user_data_dir)

        try:
            yield context
        finally:
            await context.close()

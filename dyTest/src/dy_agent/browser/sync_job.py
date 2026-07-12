"""在独立线程中运行同步 Playwright 任务。"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import Any, TypeVar

from playwright.sync_api import sync_playwright

from dy_agent.browser.profile_lock import account_profile_lock
from dy_agent.browser.stealth import STEALTH_INIT_SCRIPT, STEALTH_LAUNCH_ARGS
from dy_agent.browser.sync_login import DpPage, ensure_login_sync
from dy_agent.core.config import AccountConfig, YamlSettings, get_env_settings

T = TypeVar("T")


def _init_playwright_thread() -> None:
    if sys.platform != "win32":
        return
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)


def _launch_persistent(settings: YamlSettings, account_id: str, *, headless: bool | None = None):
    _init_playwright_thread()
    env = get_env_settings()
    user_data_dir = settings.paths.resolve("profiles_root") / account_id / "user_data"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    if headless is None:
        headless = env.playwright_headless or settings.browser.headless
    slow_mo = env.playwright_slow_mo or settings.browser.slow_mo
    channel = (env.playwright_channel or settings.browser.channel or "").strip()

    launch_kwargs: dict[str, Any] = {
        "headless": headless,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "args": STEALTH_LAUNCH_ARGS,
        "ignore_default_args": ["--enable-automation"],
    }
    if channel:
        launch_kwargs["channel"] = channel
    if slow_mo:
        launch_kwargs["slow_mo"] = slow_mo

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(str(user_data_dir), **launch_kwargs)
    context.add_init_script(STEALTH_INIT_SCRIPT)
    context.set_default_timeout(settings.browser.default_timeout_ms)
    page = context.pages[0] if context.pages else context.new_page()
    return pw, context, page


def run_sync_browser_job(
    settings: YamlSettings,
    account: AccountConfig,
    job: Callable[[DpPage], T],
) -> T:
    with account_profile_lock(settings, account.account_id, reason="browser_job"):
        pw, context, page = _launch_persistent(settings, account.account_id)
        try:
            dp = ensure_login_sync(account, page)
            if dp.context is None:
                dp = DpPage(page, context)
            return job(dp)
        finally:
            try:
                if not page.is_closed():
                    page.evaluate("window.onbeforeunload = null;")
            except Exception:
                pass
            context.close()
            pw.stop()


async def run_browser_job_async(
    settings: YamlSettings,
    account: AccountConfig,
    job: Callable[[DpPage], T],
) -> T:
    return await asyncio.to_thread(run_sync_browser_job, settings, account, job)

"""店铺浏览器会话：登录检测 + 页面封装。"""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import BrowserContext, Page

from pdd_agent.browser.human import human_click, human_pause, human_type
from pdd_agent.core.config import AccountConfig, YamlSettings
from pdd_agent.core.exceptions import BrowserError
from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)

HOME_URL = "https://mms.pinduoduo.com/home/"
# 点击登录后若出现拼图滑块，需人工在浏览器窗口拖动；此期间延长等待
CAPTCHA_WAIT_SEC = 180
NORMAL_LOGIN_WAIT_SEC = 30
_CAPTCHA_HINTS = ("请向右滑块", "完成拼图", "滑块")


@dataclass
class BrowserSession:
    """绑定店铺账号与 Playwright Page，供各 Skill 节点复用。"""

    account: AccountConfig
    context: BrowserContext
    page: Page

    @classmethod
    async def open(cls, account: AccountConfig, context: BrowserContext) -> BrowserSession:
        """复用持久化 Context 的首个标签页（更接近日常浏览器）。"""
        page = context.pages[0] if context.pages else await context.new_page()
        return cls(account=account, context=context, page=page)

    async def ensure_login(self, settings: YamlSettings) -> None:
        """
        打开商家后台首页；若跳转到 login 页则用配置中的账号密码登录。
        已缓存 Session 时 URL 不含 login，直接返回。
        """
        account_id = self.account.account_id
        page = self.page
        logger.info("[%s] checking login", account_id)

        await page.goto(HOME_URL, wait_until="domcontentloaded")
        await human_pause(1200, 2200)

        if "login" not in page.url:
            logger.info("[%s] session reused", account_id)
            return

        if not self.account.username or not self.account.password:
            raise BrowserError(f"[{account_id}] missing username/password")

        logger.info("[%s] performing password login", account_id)
        tab = page.get_by_text("账号登录", exact=True)
        if await tab.count():
            await human_click(tab, page)
            await human_pause(600, 1200)

        await human_type(page.locator("#usernameId"), self.account.username)
        await human_pause(400, 900)
        await human_type(page.locator("#passwordId"), self.account.password)
        await human_pause(500, 1100)
        await human_click(page.get_by_text("登录", exact=True), page)
        await human_pause(1200, 2000)

        wait_sec = CAPTCHA_WAIT_SEC if await self._has_slider_captcha(page) else NORMAL_LOGIN_WAIT_SEC
        if wait_sec == CAPTCHA_WAIT_SEC:
            logger.warning(
                "[%s] 检测到滑块验证码 — 请在弹出的浏览器窗口手动拖动滑块，无需录屏",
                account_id,
            )

        for remaining in range(wait_sec, 0, -1):
            if "login" not in page.url:
                logger.info("[%s] login success", account_id)
                return
            if wait_sec == CAPTCHA_WAIT_SEC and remaining % 15 == 0:
                logger.info("[%s] 等待人工完成滑块… 剩余约 %ss", account_id, remaining)
            await page.wait_for_timeout(1000)

        if wait_sec == CAPTCHA_WAIT_SEC:
            raise BrowserError(
                f"[{account_id}] 滑块验证超时：请在 headless=false 的浏览器窗口手动完成拼图后再试"
            )
        raise BrowserError(f"[{account_id}] login timeout")

    async def _has_slider_captcha(self, page: Page) -> bool:
        """页面上是否出现拼多多拼图滑块。"""
        for hint in _CAPTCHA_HINTS:
            if await page.get_by_text(hint).count():
                return True
        return False

    async def screenshot_on_error(self, path: str) -> None:
        """失败时全页截图，便于排查页面状态。"""
        try:
            await self.page.screenshot(path=path, full_page=True)
            logger.info("[%s] screenshot saved: %s", self.account.account_id, path)
        except Exception as exc:
            logger.warning("screenshot failed: %s", exc)

"""店铺浏览器会话：登录检测 + 页面封装。"""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import BrowserContext, Page

from pdd_agent.core.config import AccountConfig, YamlSettings
from pdd_agent.core.exceptions import BrowserError
from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)

HOME_URL = "https://mms.pinduoduo.com/home/"


@dataclass
class BrowserSession:
    """绑定店铺账号与 Playwright Page，供各 Skill 节点复用。"""

    account: AccountConfig
    context: BrowserContext
    page: Page

    @classmethod
    async def open(cls, account: AccountConfig, context: BrowserContext) -> BrowserSession:
        """在已有 Context 中新建标签页。"""
        page = await context.new_page()
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
        await page.wait_for_timeout(1500)

        if "login" not in page.url:
            logger.info("[%s] session reused", account_id)
            return

        if not self.account.username or not self.account.password:
            raise BrowserError(f"[{account_id}] missing username/password")

        logger.info("[%s] performing password login", account_id)
        tab = page.get_by_text("账号登录", exact=True)
        if await tab.count():
            await tab.click()
            await page.wait_for_timeout(800)

        await page.locator("#usernameId").fill(self.account.username)
        await page.locator("#passwordId").fill(self.account.password)
        await page.get_by_text("登录", exact=True).click()

        # 最多等待 30 秒离开登录页
        for _ in range(30):
            if "login" not in page.url:
                logger.info("[%s] login success", account_id)
                return
            await page.wait_for_timeout(1000)

        raise BrowserError(f"[{account_id}] login timeout")

    async def screenshot_on_error(self, path: str) -> None:
        """失败时全页截图，便于排查页面状态。"""
        try:
            await self.page.screenshot(path=path, full_page=True)
            logger.info("[%s] screenshot saved: %s", self.account.account_id, path)
        except Exception as exc:
            logger.warning("screenshot failed: %s", exc)

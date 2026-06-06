"""Page Object 基类：后续按页面拆 listing_category.py、listing_specs.py 等。"""

from playwright.async_api import Page


class BasePage:
    """封装 Playwright Page 的通用导航。"""

    def __init__(self, page: Page) -> None:
        self.page = page

    async def goto(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded")

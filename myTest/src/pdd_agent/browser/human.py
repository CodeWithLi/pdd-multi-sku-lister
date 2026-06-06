"""模拟真人操作：随机延迟、逐字输入、曲线拖动。"""

from __future__ import annotations

import asyncio
import random

from playwright.async_api import Locator, Page


async def human_pause(min_ms: int = 300, max_ms: int = 900) -> None:
    """步骤间随机停顿。"""
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


async def human_click(locator: Locator, page: Page) -> None:
    """先移动鼠标再点击，避免瞬移点击。"""
    await locator.scroll_into_view_if_needed()
    box = await locator.bounding_box()
    if box:
        x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
        await page.mouse.move(x, y, steps=random.randint(8, 18))
        await human_pause(80, 220)
    await locator.click(delay=random.randint(50, 150))


async def human_type(locator: Locator, text: str) -> None:
    """逐字输入，间隔随机。"""
    await locator.click()
    await locator.fill("")
    for ch in text:
        await locator.type(ch, delay=random.randint(60, 180))
        if random.random() < 0.08:
            await human_pause(120, 350)

"""发布页变体识别与路由（预留多页面分支，类似 PDD category_page_flow）。"""

from __future__ import annotations

from typing import Literal

from playwright.sync_api import Page

from dy_agent.core.exceptions import BrowserError
from dy_agent.domain.models import ListingUnit
from dy_agent.skills.listing.listing_options import ListingOptions

PublishPageVariant = Literal["standard_v1", "unknown"]


def _page_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5_000)
    except Exception:
        return ""


def detect_publish_page_variant(page: Page) -> PublishPageVariant:
    """识别当前发布页 UI 变体。"""
    text = _page_text(page)
    if "商品发布" in text and "主图上传" in text and "商品标题" in text:
        return "standard_v1"
    return "unknown"


def run_publish_page_step1(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """
    发布页第一步：主图 → AI 标题 → 类目 → 下一步。
    按页面变体路由；未知变体抛错，便于后续新增分支。
    """
    variant = detect_publish_page_variant(page)
    label = unit.listing_label

    if variant == "standard_v1":
        from dy_agent.skills.listing.publish_page_standard_v1 import run_standard_v1_step1

        return run_standard_v1_step1(page, account_id, unit, options)

    raise BrowserError(
        f"[{account_id}] [{label}] 未识别的发布页变体，请新增 publish_page_* 处理器；"
        f"当前 URL={page.url}"
    )

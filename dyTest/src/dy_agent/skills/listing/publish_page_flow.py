"""发布页变体识别与路由（预留多页面分支，类似 PDD category_page_flow）。"""

from __future__ import annotations

import time
from typing import Literal

from playwright.sync_api import Page

from dy_agent.core.exceptions import BrowserError
from dy_agent.domain.models import ListingUnit
from dy_agent.skills.listing.listing_options import ListingOptions

PublishPageVariant = Literal["standard_v1", "unknown"]

PUBLISH_PAGE_READY_TIMEOUT = 45.0
PUBLISH_PAGE_READY_POLL = 1.0


def _page_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5_000)
    except Exception:
        return ""


def _is_known_publish_url(url: str) -> bool:
    u = (url or "").lower()
    return "/ffa/g/create" in u or "/ffa/mcreate" in u


def _has_title_field(page: Page) -> bool:
    try:
        return (
            page.locator(
                'input[placeholder*="商品标题"], input[placeholder*="标题"], '
                'textarea[placeholder*="商品标题"], textarea[placeholder*="标题"]'
            ).count()
            > 0
        )
    except Exception:
        return False


def _has_main_image_section(text: str) -> bool:
    return "主图上传" in text or "上传主图" in text


def _matches_standard_v1_text(text: str) -> bool:
    if "商品发布" in text and "主图上传" in text and "商品标题" in text:
        return True
    has_publish = "商品发布" in text or "发布商品" in text
    has_title = "商品标题" in text or "标题" in text
    return has_publish and _has_main_image_section(text) and has_title


def _matches_standard_v1_dom(page: Page, text: str) -> bool:
    if not _is_known_publish_url(page.url):
        return False
    try:
        has_file_input = page.locator('input[type="file"]').count() > 0
    except Exception:
        has_file_input = False
    return has_file_input and _has_title_field(page) and _has_main_image_section(text)


def detect_publish_page_variant(page: Page) -> PublishPageVariant:
    """识别当前发布页 UI 变体。"""
    text = _page_text(page)
    if _matches_standard_v1_text(text) or _matches_standard_v1_dom(page, text):
        return "standard_v1"
    return "unknown"


def wait_for_publish_page_ready(
    page: Page,
    *,
    timeout: float = PUBLISH_PAGE_READY_TIMEOUT,
) -> PublishPageVariant:
    """轮询等待发布页 SPA 渲染完成后再识别变体。"""
    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        variant = detect_publish_page_variant(page)
        if variant != "unknown":
            return variant
        last_text = _page_text(page)
        time.sleep(PUBLISH_PAGE_READY_POLL)
    return detect_publish_page_variant(page) if last_text else "unknown"


def detect_publish_page_step2(page: Page) -> bool:
    """是否已在「图文信息」页（下一步之后）。"""
    text = _page_text(page)
    return "白底图" in text and "商品详情" in text


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
    label = unit.listing_label
    variant = wait_for_publish_page_ready(page)

    if variant == "standard_v1":
        from dy_agent.skills.listing.publish_page_standard_v1 import run_standard_v1_step1

        return run_standard_v1_step1(page, account_id, unit, options)

    snippet = _page_text(page).replace("\n", " ").strip()[:160]
    raise BrowserError(
        f"[{account_id}] [{label}] 未识别的发布页变体，请新增 publish_page_* 处理器；"
        f"当前 URL={page.url}"
        + (f"；页面摘要={snippet!r}" if snippet else "")
    )


def run_publish_page_step2(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """
    发布页第二步：白底图(9) + 商品详情图(6~8)。
    在 step1 点击「下一步」后调用。
    """
    from dy_agent.skills.listing.publish_page_standard_v1 import run_standard_v1_step2

    return run_standard_v1_step2(page, account_id, unit, options)


def detect_publish_page_step3(page: Page) -> bool:
    """是否已在手动规格/价格库存页。"""
    from dy_agent.skills.listing.publish_price_stock import is_manual_spec_page

    return is_manual_spec_page(page)


def run_publish_page_step3(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """发布页第三步：价格库存 → 切换手动填写。"""
    from dy_agent.skills.listing.publish_page_standard_v1 import run_standard_v1_step3

    return run_standard_v1_step3(page, account_id, unit, options)


def run_publish_page_step4(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """发布页第四步：规格维度填表（抖店创建类型流程）。"""
    from dy_agent.skills.listing.publish_page_standard_v1 import run_standard_v1_step4

    return run_standard_v1_step4(page, account_id, unit, options)


def run_publish_page_step5(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
    *,
    defaults: dict[str, str] | None = None,
) -> dict:
    """发布页第五步：价格 / 库存 / 商家编码。"""
    from dy_agent.skills.listing.publish_page_standard_v1 import run_standard_v1_step5

    return run_standard_v1_step5(page, account_id, unit, options, defaults=defaults)


def run_publish_page_step6(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """发布页第六步：发布商品 + 商品列表核验。"""
    from dy_agent.skills.listing.publish_page_standard_v1 import run_standard_v1_step6

    return run_standard_v1_step6(page, account_id, unit, options)

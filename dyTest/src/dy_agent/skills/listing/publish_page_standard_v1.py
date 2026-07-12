"""标准发布页变体 v1：主图 → AI 标题 → 类目 → 下一步。"""

from __future__ import annotations

import time

from playwright.sync_api import Page

from dy_agent.domain.models import ListingUnit
from dy_agent.skills.listing.listing_accessory_pricing import apply_accessory_pricing_if_enabled
from dy_agent.skills.listing.listing_options import ListingOptions
from dy_agent.skills.listing.listing_spec_pipeline import prepare_spec_pipeline_flags
from dy_agent.skills.listing.publish_ai_title import wait_and_apply_page_ai_title
from dy_agent.skills.listing.publish_category import wait_and_select_first_category
from dy_agent.skills.listing.publish_main_images import upload_main_carousel_images
from dy_agent.skills.listing.publish_next_step import click_publish_next_and_advance


def run_standard_v1_step1(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    label = unit.listing_label
    spec_flags = prepare_spec_pipeline_flags(options)
    pricing_flags = apply_accessory_pricing_if_enabled(unit, options)

    uploaded = upload_main_carousel_images(
        page,
        account_id,
        label,
        unit.carousel_images,
    )
    time.sleep(1)

    title = wait_and_apply_page_ai_title(
        page,
        account_id,
        label,
        title_mode=options.title_mode,
    )
    time.sleep(2)

    category = wait_and_select_first_category(
        page,
        account_id,
        label,
        burst_demo=options.category_next_burst_demo,
    )

    next_ok, next_err = click_publish_next_and_advance(
        page,
        account_id,
        label,
        burst_demo=options.category_next_burst_demo,
    )
    if not next_ok:
        reason = next_err or "next_step_failed"
        raise RuntimeError(f"[{account_id}] [{label}] 发布页「下一步」失败: {reason}")

    return {
        "listing_label": label,
        "status": "step1_done",
        "message": "发布页第一步完成（主图/AI标题/类目/下一步）",
        "merchant_code": unit.merchant_code,
        "main_images_uploaded": uploaded,
        "title": title,
        "category": category,
        "publish_variant": "standard_v1",
        "spec_flags": spec_flags,
        "pricing_flags": pricing_flags,
        "page_url": page.url,
    }

"""抖店多规格上架主流程。"""

from __future__ import annotations

import time
from typing import Any

from dy_agent.browser.sync_login import DpPage
from dy_agent.core.logging import get_logger
from dy_agent.domain.models import ListingUnit
from dy_agent.skills.listing.listing_options import ListingOptions, listing_options_from_settings
from dy_agent.skills.listing.publish_navigate import open_publish_page
from dy_agent.skills.listing.publish_page_flow import run_publish_page_step1
from dy_agent.core.config import load_yaml_settings

logger = get_logger(__name__)


def upload_one_listing(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict[str, Any]:
    label = unit.listing_label
    raw = page.raw
    context = page.context
    if context is None:
        raise RuntimeError(f"[{account_id}] [{label}] 缺少 BrowserContext，无法打开发布页新标签")

    publish_page = open_publish_page(raw, context, account_id, label)
    page._page = publish_page  # noqa: SLF001 — 切换到发布标签页

    result = run_publish_page_step1(publish_page, account_id, unit, options)
    result["sku_count"] = len(unit.skus)
    return result


def run_listing_uploads(
    page: DpPage,
    account_id: str,
    units: list[ListingUnit],
    *,
    category_keyword: str = "",
    title_mode: str = "page_ai",
    defaults: dict[str, str] | None = None,
    run_id: str = "",
    slot_alignment_test: bool = False,
    spec_fill_verify_test: bool = False,
    primary_style_first_test: bool = False,
    category_next_burst_demo: bool = True,
    accessory_cost_pricing: bool = False,
    accessory_tiered_float: bool = False,
) -> list[dict[str, Any]]:
    if slot_alignment_test and spec_fill_verify_test:
        raise ValueError("spec_fill_verify_test 与 slot_alignment_test 不能同时开启")

    settings = load_yaml_settings()
    base_options = listing_options_from_settings(settings, category_keyword=category_keyword)
    options = ListingOptions(
        slot_alignment_test=slot_alignment_test,
        spec_fill_verify_test=spec_fill_verify_test,
        primary_style_first_test=primary_style_first_test,
        category_next_burst_demo=category_next_burst_demo,
        accessory_cost_pricing=accessory_cost_pricing,
        accessory_tiered_float=accessory_tiered_float,
        title_mode=title_mode or base_options.title_mode,
        category_keyword=category_keyword or base_options.category_keyword,
    )

    results: list[dict[str, Any]] = []
    for idx, unit in enumerate(units):
        if idx > 0:
            print(f"\n[{account_id}] 等待 5 秒后上架下一单元 [{unit.listing_label}]…\n", flush=True)
            time.sleep(5)
        try:
            logger.info("[%s] listing start: %s", account_id, unit.listing_label)
            item = upload_one_listing(page, account_id, unit, options)
            item["run_id"] = run_id
            results.append(item)
        except Exception as exc:
            logger.exception("[%s] listing failed: %s", account_id, unit.listing_label)
            results.append(
                {
                    "listing_label": unit.listing_label,
                    "status": "failed",
                    "message": str(exc),
                    "merchant_code": unit.merchant_code,
                    "run_id": run_id,
                }
            )
    return results

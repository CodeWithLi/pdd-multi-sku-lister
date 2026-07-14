"""抖店多规格上架主流程。"""

from __future__ import annotations

import time
from typing import Any

from dy_agent.browser.sync_login import DpPage
from dy_agent.core.logging import get_logger
from dy_agent.domain.models import ListingUnit
from dy_agent.skills.listing.listing_options import ListingOptions, listing_options_from_settings
from dy_agent.skills.listing.listing_published_product import persist_listed_product_item
from dy_agent.skills.listing.listing_unit_prep import prepare_listing_unit
from dy_agent.skills.listing.publish_navigate import open_publish_page
from dy_agent.skills.listing.publish_page_flow import (
    run_publish_page_step1,
    run_publish_page_step2,
    run_publish_page_step3,
    run_publish_page_step4,
    run_publish_page_step5,
    run_publish_page_step6,
)
from dy_agent.core.config import load_yaml_settings

logger = get_logger(__name__)


def upload_one_listing(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
    *,
    defaults: dict[str, str] | None = None,
) -> dict[str, Any]:
    label = unit.listing_label
    raw = page.raw
    context = page.context
    if context is None:
        raise RuntimeError(f"[{account_id}] [{label}] 缺少 BrowserContext，无法打开发布页新标签")

    publish_page = open_publish_page(raw, context, account_id, label)
    page._page = publish_page  # noqa: SLF001 — 切换到发布标签页

    settings = load_yaml_settings()
    fill_defaults = defaults if defaults is not None else dict(settings.multi_spec.defaults or {})

    prep = prepare_listing_unit(unit, options, account_id=account_id)

    result = run_publish_page_step1(publish_page, account_id, unit, options)
    step2 = run_publish_page_step2(publish_page, account_id, unit, options)
    step3 = run_publish_page_step3(publish_page, account_id, unit, options)
    step4 = run_publish_page_step4(publish_page, account_id, unit, options)
    step5 = run_publish_page_step5(
        publish_page, account_id, unit, options, defaults=fill_defaults
    )
    step6 = run_publish_page_step6(publish_page, account_id, unit, options)
    result.update(step2)
    result.update(step3)
    result.update(step4)
    result.update(step5)
    result.update(step6)
    result["product_code"] = unit.product_code
    result["family_code"] = unit.family_code
    result["image_set"] = unit.image_set
    result["unit_prep"] = prep
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
    spec_fill_verify_test: bool = True,
    primary_style_first_test: bool = True,
    category_next_burst_demo: bool = True,
    accessory_cost_pricing: bool = True,
    accessory_tiered_float: bool = True,
    brand_name: str = "无品牌",
    manufacturer_name: str = "",
) -> list[dict[str, Any]]:
    if slot_alignment_test and spec_fill_verify_test:
        raise ValueError("spec_fill_verify_test 与 slot_alignment_test 不能同时开启")

    settings = load_yaml_settings()
    base_options = listing_options_from_settings(settings, category_keyword=category_keyword)
    fill_defaults = defaults if defaults is not None else dict(settings.multi_spec.defaults or {})
    options = ListingOptions(
        slot_alignment_test=slot_alignment_test,
        spec_fill_verify_test=spec_fill_verify_test,
        primary_style_first_test=primary_style_first_test,
        category_next_burst_demo=category_next_burst_demo,
        accessory_cost_pricing=accessory_cost_pricing,
        accessory_tiered_float=accessory_tiered_float,
        title_mode=title_mode or base_options.title_mode,
        category_keyword=category_keyword or base_options.category_keyword,
        brand_name=brand_name or base_options.brand_name or "无品牌",
        manufacturer_name=manufacturer_name if manufacturer_name is not None else base_options.manufacturer_name,
    )

    results: list[dict[str, Any]] = []
    for idx, unit in enumerate(units):
        if idx > 0:
            print(f"\n[{account_id}] 等待 5 秒后上架下一单元 [{unit.listing_label}]…\n", flush=True)
            time.sleep(5)
        try:
            logger.info("[%s] listing start: %s", account_id, unit.listing_label)
            item = upload_one_listing(
                page, account_id, unit, options, defaults=fill_defaults
            )
            item["run_id"] = run_id
            # 写飞书前强制按当前页刷新店铺名，避免误用旧缓存「精选联盟」
            try:
                from dy_agent.browser.shop_display_name import refresh_shop_display_name
                from dy_agent.browser.sync_login import resolve_account_phone
                from dy_agent.core.config import load_yaml_settings as _load_cfg
                from dy_agent.db.repositories import get_account_config

                _acc = get_account_config(_load_cfg(), account_id)
                shop_name = refresh_shop_display_name(
                    account_id,
                    page,
                    login_phone=resolve_account_phone(_acc) if _acc else "",
                )
                if shop_name:
                    item["shop_display_name"] = shop_name
            except Exception as shop_exc:
                logger.warning("[%s] refresh shop name before feishu failed: %s", account_id, shop_exc)

            saved = persist_listed_product_item(run_id, account_id, unit, item)
            if saved:
                item["db_saved"] = True
                item["published_product"] = saved
            if str(item.get("status") or "") in {"success", "listed"}:
                from dy_agent.integrations.feishu.dy_upload_sync import (
                    schedule_feishu_dy_upload_log_from_listing,
                )

                schedule_feishu_dy_upload_log_from_listing(
                    account_id=account_id,
                    unit=unit,
                    item=item,
                )
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

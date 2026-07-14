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
from dy_agent.skills.listing.publish_media_images import upload_media_images_step2
from dy_agent.skills.listing.publish_next_step import click_publish_next_and_advance
from dy_agent.skills.listing.publish_price_stock import switch_to_manual_price_stock


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

    # 「类目属性」在点下一步之后才出现（基础信息 Tab），不要在下一步前等待
    from dy_agent.skills.listing.publish_category_attrs import fill_category_attributes

    time.sleep(1)
    category_attrs = fill_category_attributes(
        page,
        account_id,
        label,
        brand=options.brand_name or "无品牌",
        manufacturer_name=options.manufacturer_name or "",
    )

    return {
        "listing_label": label,
        "status": "step1_done",
        "message": "发布页第一步完成（主图/AI标题/类目/下一步/类目属性）",
        "merchant_code": unit.merchant_code,
        "main_images_uploaded": uploaded,
        "title": title,
        "category": category,
        "category_attrs": category_attrs,
        "publish_variant": "standard_v1",
        "spec_flags": spec_flags,
        "pricing_flags": pricing_flags,
        "page_url": page.url,
    }


def run_standard_v1_step2(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """发布页第二步：白底图(9) → 商品详情图(6~8)。"""
    label = unit.listing_label
    media = upload_media_images_step2(
        page,
        account_id,
        label,
        material_image=unit.material_image,
        detail_images=unit.detail_images,
    )
    return {
        "listing_label": label,
        "status": "step2_done",
        "message": "发布页第二步完成（白底图/商品详情图）",
        "merchant_code": unit.merchant_code,
        "publish_variant": "standard_v1",
        "white_background_uploaded": media["white_background_uploaded"],
        "detail_images_uploaded": media["detail_images_uploaded"],
        "page_url": page.url,
    }


def run_standard_v1_step3(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """发布页第三步：价格库存 → 切换手动填写。"""
    label = unit.listing_label
    switch = switch_to_manual_price_stock(page, account_id, label)
    return {
        "listing_label": label,
        "status": "step3_done",
        "message": "发布页第三步完成（价格库存/切换手动填写）",
        "merchant_code": unit.merchant_code,
        "publish_variant": "standard_v1",
        "price_stock_tab_clicked": switch["price_stock_tab_clicked"],
        "manual_switch_clicked": switch["manual_switch_clicked"],
        "already_manual": switch["already_manual"],
        "page_url": page.url,
    }


def run_standard_v1_step4(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """发布页第四步：颜色分类 / 尺寸大小（抖店「创建类型」填表）。"""
    from dy_agent.skills.listing.listing_spec_pipeline import run_spec_fill_pipeline

    label = unit.listing_label
    spec_result = run_spec_fill_pipeline(page, account_id, unit, options)
    return {
        "listing_label": label,
        "status": "step4_done",
        "message": "发布页第四步完成（颜色分类/尺寸大小 创建类型填表）",
        "merchant_code": unit.merchant_code,
        "publish_variant": "standard_v1",
        "spec_fill": spec_result,
        "page_url": page.url,
    }


def run_standard_v1_step5(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
    *,
    defaults: dict[str, str] | None = None,
) -> dict:
    """发布页第五步：价格 / 现货库存 / 商家编码填表。"""
    from dy_agent.skills.listing.listing_spec_pipeline import run_spec_price_fill_pipeline

    label = unit.listing_label
    price_result = run_spec_price_fill_pipeline(
        page,
        account_id,
        unit,
        options,
        defaults=defaults,
    )
    return {
        "listing_label": label,
        "status": "step5_done",
        "message": "发布页第五步完成（价格/库存/商家编码）",
        "merchant_code": unit.merchant_code,
        "publish_variant": "standard_v1",
        "price_fill": price_result,
        "page_url": page.url,
    }


def run_standard_v1_step6(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """发布页第六步：发布商品 → 等待成功 → 商品列表核验。"""
    from dy_agent.skills.listing.goods_list_capture import capture_goods_by_merchant_code
    from dy_agent.skills.listing.publish_submit import submit_and_return_goods_list

    label = unit.listing_label
    merchant_code = unit.merchant_code
    submit_result = submit_and_return_goods_list(page, account_id, label)
    capture = capture_goods_by_merchant_code(
        page,
        account_id,
        label,
        merchant_code,
    )

    captured = capture.get("status") == "captured" and bool(capture.get("dy_product_id"))
    if not captured:
        raise RuntimeError(
            f"[{account_id}] [{label}] 发布后商品列表核验失败: "
            f"{capture.get('message') or capture.get('status') or 'not_found'}"
        )

    return {
        "listing_label": label,
        "status": "success",
        "message": "发布完成（商品列表已抓取 ID/状态/上架时间/链接）",
        "merchant_code": merchant_code,
        "publish_variant": "standard_v1",
        "publish_submit": submit_result,
        "goods_list_capture": capture,
        "dy_product_id": capture.get("dy_product_id") or "",
        "list_status": capture.get("list_status") or "",
        "listed_at": capture.get("listed_at") or "",
        "product_link": capture.get("product_link") or "",
        "product_link_ok": bool(capture.get("product_link_ok")),
        "page_url": page.url,
    }

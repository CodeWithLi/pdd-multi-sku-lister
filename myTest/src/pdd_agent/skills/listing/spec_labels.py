"""款式（AI 颜色）+ 尺寸（商品表分组）规格名解析。"""

from __future__ import annotations

from pathlib import Path

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.llm.vision import detect_product_color
from pdd_agent.skills.listing.pdd_product_catalog import (
    get_catalog_entry,
    get_pdd_product_catalog,
    resolve_size_label,
)


def uses_pdd_spec_catalog(style_code: str) -> bool:
    catalog = get_pdd_product_catalog()
    return bool(catalog) and style_code.strip().upper() in catalog


def pick_style_reference_image(unit: ListingUnit, style_code: str) -> Path | None:
    """优先用单款规格图 {code}.png，否则用该款式任意预览图或主图。"""
    style_norm = style_code.strip().upper()
    for sku in unit.skus:
        if sku.style_code.strip().upper() != style_norm:
            continue
        if sku.combo_folder.strip().upper() == style_norm and sku.preview_image.is_file():
            return sku.preview_image
    for sku in unit.skus:
        if sku.style_code.strip().upper() == style_norm and sku.preview_image.is_file():
            return sku.preview_image
    if unit.product_code.strip().upper() == style_norm and unit.carousel_images:
        return unit.carousel_images[0]
    return None


def resolve_style_colors(unit: ListingUnit, account_id: str = "") -> dict[str, str]:
    catalog = get_pdd_product_catalog()
    colors: dict[str, str] = {}
    for style_code in unit.style_codes:
        entry = catalog.get(style_code.strip().upper())
        image = pick_style_reference_image(unit, style_code)
        if image:
            prefix = f"[{account_id}] " if account_id else ""
            print(f"{prefix}[{unit.listing_label}] AI识别款式颜色：{style_code} ← {image.name}", flush=True)
            colors[style_code] = detect_product_color(image, catalog_entry=entry)
        elif entry:
            colors[style_code] = entry.color_spec[:8]
        else:
            colors[style_code] = style_code
    return colors


def apply_spec_labels_to_sku(sku: SkuCombo, style_colors: dict[str, str], catalog: dict) -> None:
    sku.style_name = style_colors.get(sku.style_code, sku.style_name or sku.style_code)
    sku.model_name = resolve_size_label(sku.style_code, sku.model_code, catalog)


def enrich_listing_unit_specs(unit: ListingUnit, account_id: str = "") -> None:
    """将 SKU 的款式/尺寸名改为 AI 颜色 + 商品表分组尺寸。"""
    if not unit.skus:
        return
    if not any(uses_pdd_spec_catalog(sku.style_code) for sku in unit.skus):
        return

    catalog = get_pdd_product_catalog()
    style_colors = resolve_style_colors(unit, account_id=account_id)

    seen_sizes: list[str] = []
    for sku in unit.skus:
        apply_spec_labels_to_sku(sku, style_colors, catalog)
        if sku.model_name not in seen_sizes:
            seen_sizes.append(sku.model_name)

    unit.style_codes = list(dict.fromkeys(sku.style_code for sku in unit.skus))
    unit.model_codes = seen_sizes

"""同套图兄弟款：平台不适用跳过后不再并入规格（对齐拼多多）。"""

from __future__ import annotations

from pathlib import Path

from dy_agent.domain.models import ListingUnit


def should_include_sibling_spec_code(
    sibling_code: str,
    *,
    listing_product_code: str,
) -> bool:
    """
    兄弟款是否参与当前上架单元的规格。

    已「平台不适用跳过」的兄弟编码不参与；当前正在上架的商品编码始终保留。
    """
    code = str(sibling_code or "").strip()
    current = str(listing_product_code or "").strip()
    if not code:
        return False
    if current and code.upper() == current.upper():
        return True
    try:
        from dy_agent.integrations.feishu.platform_skip_dedupe_cache import (
            is_platform_skip_merchant_code,
        )

        if is_platform_skip_merchant_code(code, require_enabled=False):
            return False
    except Exception:
        pass
    return True


def filter_sibling_dirs_for_listing_specs(
    sibling_dirs: list[Path],
    *,
    listing_product_code: str,
) -> list[Path]:
    return [
        path
        for path in sibling_dirs
        if should_include_sibling_spec_code(
            path.name,
            listing_product_code=listing_product_code,
        )
    ]


def filter_listing_unit_skus_by_platform_skip(unit: ListingUnit) -> list[str]:
    """从 ListingUnit 剔除已跳过的兄弟款 SKU（就地修改）。"""
    removed_styles: list[str] = []
    kept = []
    for sku in unit.skus:
        style_code = str(sku.style_code or "").strip()
        if should_include_sibling_spec_code(
            style_code,
            listing_product_code=unit.product_code,
        ):
            kept.append(sku)
        elif style_code and style_code not in removed_styles:
            removed_styles.append(style_code)
    if not removed_styles:
        return []
    unit.skus = kept
    unit.style_codes = list(dict.fromkeys(s.style_code for s in unit.skus if s.style_code))
    unit.model_codes = list(
        dict.fromkeys(
            (s.model_name or s.model_code)
            for s in unit.skus
            if (s.model_name or s.model_code)
        )
    )
    return removed_styles

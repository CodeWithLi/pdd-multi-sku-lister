"""配件成本定价 — 浮动继承与同配件同价（独立子模块）。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdd_agent.skills.listing.pdd_product_catalog import (
    PddProductEntry,
    _norm_code,
    find_catalog_entry,
    product_code_family_key,
)

if TYPE_CHECKING:
    from pdd_agent.domain.models import ListingUnit


@dataclass(frozen=True)
class _SkuPricingRow:
    sku_index: int
    main_key: str
    main_price: float
    accessory_cost_sum: float
    align_key: str
    has_accessories: bool


def combo_align_key(
    main_code: str,
    accessory_codes: list[str],
    catalog: dict[str, PddProductEntry],
) -> str:
    """跨主商品对齐键：主商品族 + 配件族序列（去末位变体字母），如 BD046|YKL001+YKL008。"""
    if not accessory_codes:
        return ""
    main_family = main_group_key(catalog, main_code)
    acc_families = sorted(
        dict.fromkeys(
            product_code_family_key(code)
            for code in accessory_codes
            if product_code_family_key(code)
        )
    )
    if not acc_families:
        return ""
    return f"{main_family}|{'+'.join(acc_families)}"


def accessory_align_key(
    accessory_codes: list[str],
    *,
    main_code: str = "",
    catalog: dict[str, PddProductEntry] | None = None,
) -> str:
    """兼容旧调用；请优先使用 combo_align_key(main_code, accessory_codes, catalog)。"""
    if main_code and catalog is not None:
        return combo_align_key(main_code, accessory_codes, catalog)
    families = [
        product_code_family_key(code)
        for code in accessory_codes
        if product_code_family_key(code)
    ]
    if len(families) == 1:
        return families[0]
    return ""


def main_group_key(catalog: dict[str, PddProductEntry], main_code: str) -> str:
    entry = find_catalog_entry(catalog, main_code)
    canonical = entry.code if entry else main_code
    return product_code_family_key(canonical)


def reconcile_accessory_cost_floats(
    rows: list[_SkuPricingRow],
    *,
    listing_scope: str,
    float_min: float,
    float_max: float,
) -> dict[int, tuple[float, float]]:
    """按 SKU 顺序确定浮动并返回 sku_index -> (float_delta, group_price)。"""
    scope = str(listing_scope or "").strip() or "__default__"
    fmin = max(0.0, float(float_min))
    fmax = max(fmin, float(float_max))

    main_floats: dict[tuple[str, str], float] = {}
    combo_anchors: dict[tuple[str, str], float] = {}

    for row in rows:
        main_sk = (scope, row.main_key)
        align_sk = (scope, row.align_key) if row.align_key else None

        if align_sk and align_sk in combo_anchors:
            anchor = combo_anchors[align_sk]
            float_delta = round(anchor - row.main_price - row.accessory_cost_sum, 2)
            main_floats[main_sk] = float_delta
            continue

        if main_sk not in main_floats:
            main_floats[main_sk] = round(random.uniform(fmin, fmax), 2)

        if align_sk and align_sk not in combo_anchors:
            float_delta = main_floats[main_sk]
            combo_anchors[align_sk] = round(
                row.main_price + row.accessory_cost_sum + float_delta,
                2,
            )

    out: dict[int, tuple[float, float]] = {}
    for row in rows:
        main_sk = (scope, row.main_key)
        align_sk = (scope, row.align_key) if row.align_key else None
        float_delta = main_floats.get(main_sk, 0.0)

        if align_sk and align_sk in combo_anchors:
            group_price = combo_anchors[align_sk]
        else:
            group_price = round(row.main_price + row.accessory_cost_sum + float_delta, 2)

        out[row.sku_index] = (float_delta, group_price)
    return out


def apply_reconciled_prices_to_unit(
    unit: ListingUnit,
    catalog: dict[str, PddProductEntry],
    *,
    listing_scope: str,
    float_min: float,
    float_max: float,
    cost_map: dict[str, float],
    lookup_accessory_cost,
    split_main_and_accessory_codes,
    bundle_model_code: str,
    parse_combo_component_codes,
    resolve_inventory,
    format_price,
    effective_single_price,
) -> None:
    """上架单元内所有 SKU 按浮动继承规则重算拼单价。"""
    rows: list[_SkuPricingRow] = []
    for index, sku in enumerate(unit.skus):
        bundle_components = None
        if _norm_code(sku.model_code) == bundle_model_code:
            bundle_components = parse_combo_component_codes(sku.combo_folder, sku.style_code)
        main_code, accessory_codes = split_main_and_accessory_codes(
            style_code=sku.style_code,
            model_code=sku.model_code,
            bundle_components=bundle_components,
        )
        if not main_code:
            continue
        entry = find_catalog_entry(catalog, main_code)
        if not entry or float(entry.price or 0.0) <= 0:
            continue
        accessory_cost_sum = 0.0
        for code in accessory_codes:
            accessory_cost_sum += lookup_accessory_cost(code, cost_map=cost_map, catalog=catalog)
        rows.append(
            _SkuPricingRow(
                sku_index=index,
                main_key=main_group_key(catalog, main_code),
                main_price=round(float(entry.price or 0.0), 2),
                accessory_cost_sum=round(accessory_cost_sum, 2),
                align_key=combo_align_key(main_code, accessory_codes, catalog),
                has_accessories=bool(accessory_codes),
            )
        )

    if not rows:
        return

    reconciled = reconcile_accessory_cost_floats(
        rows,
        listing_scope=listing_scope,
        float_min=float_min,
        float_max=float_max,
    )

    for row in rows:
        sku = unit.skus[row.sku_index]
        _, group_price = reconciled[row.sku_index]
        bundle_components = None
        if _norm_code(sku.model_code) == bundle_model_code:
            bundle_components = parse_combo_component_codes(sku.combo_folder, sku.style_code)
        main_code, accessory_codes = split_main_and_accessory_codes(
            style_code=sku.style_code,
            model_code=sku.model_code,
            bundle_components=bundle_components,
        )
        main_entry = find_catalog_entry(catalog, main_code)
        if not main_entry:
            continue
        sku.group_price = format_price(group_price)
        sku.single_price = format_price(effective_single_price(listing_scope, group_price))
        sku.inventory = resolve_inventory(
            main_entry=main_entry,
            accessory_codes=accessory_codes,
            catalog=catalog,
            bundle_components=bundle_components,
            model_code=sku.model_code,
        )

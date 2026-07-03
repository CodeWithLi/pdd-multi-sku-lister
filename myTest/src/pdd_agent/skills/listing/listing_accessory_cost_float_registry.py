"""配件成本定价 — 主商品与配件分别浮动（独立子模块）。"""

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
class _AccessoryCostPart:
    float_key: str
    cost: float


@dataclass(frozen=True)
class _SkuPricingRow:
    sku_index: int
    main_key: str
    main_price: float
    accessories: tuple[_AccessoryCostPart, ...]
    has_accessories: bool

    @property
    def accessory_cost_sum(self) -> float:
        return round(sum(part.cost for part in self.accessories), 2)


def _price_key(price: float) -> str:
    return f"{round(float(price or 0), 2):.2f}"


def accessory_cost_group_price_floor(
    main_price: float,
    accessory_cost_sum: float = 0.0,
) -> float:
    """配件成本模式拼单价硬下限：单款不低于主商品定价；组合不低于主定价+配件成本。"""
    base = round(float(main_price or 0), 2)
    if base <= 0:
        return 0.0
    acc = round(float(accessory_cost_sum or 0), 2)
    if acc > 0:
        return round(base + acc, 2)
    return base


def clamp_accessory_cost_group_price(
    group_price: float,
    *,
    main_price: float,
    accessory_cost_sum: float = 0.0,
) -> float:
    """将拼单价钳制到合法下限之上。"""
    floor = accessory_cost_group_price_floor(main_price, accessory_cost_sum)
    return max(round(float(group_price or 0), 2), floor)


def main_group_key(catalog: dict[str, PddProductEntry], main_code: str) -> str:
    entry = find_catalog_entry(catalog, main_code)
    canonical = entry.code if entry else main_code
    return product_code_family_key(canonical)


def main_float_key(catalog: dict[str, PddProductEntry], main_code: str, main_price: float) -> str:
    """主商品浮动继承键：同族且上架定价相同才共享浮动。"""
    return f"{main_group_key(catalog, main_code)}@{_price_key(main_price)}"


def accessory_float_key(accessory_code: str, cost: float) -> str:
    """配件浮动继承键：同配件族且聚水潭成本相同才共享浮动。"""
    family = product_code_family_key(accessory_code)
    return f"{family}@{_price_key(cost)}"


def accessory_float_key_for_codes(
    accessory_codes: list[str],
    *,
    costs: list[float],
) -> list[_AccessoryCostPart]:
    parts: list[_AccessoryCostPart] = []
    for code, cost in zip(accessory_codes, costs):
        rounded = round(float(cost or 0), 2)
        parts.append(
            _AccessoryCostPart(
                float_key=accessory_float_key(code, rounded),
                cost=rounded,
            )
        )
    return parts


def _draw_float(float_min: float, float_max: float) -> float:
    fmin = max(0.0, float(float_min))
    fmax = max(fmin, float(float_max))
    return round(random.uniform(fmin, fmax), 2)


def reconcile_accessory_cost_floats(
    rows: list[_SkuPricingRow],
    *,
    listing_scope: str,
    float_min: float,
    float_max: float,
) -> dict[int, tuple[float, float, float]]:
    """返回 sku_index -> (main_float, accessory_float_sum, group_price)。"""
    scope = str(listing_scope or "").strip() or "__default__"

    main_floats: dict[tuple[str, str], float] = {}
    accessory_floats: dict[tuple[str, str], float] = {}

    for row in rows:
        main_sk = (scope, row.main_key)
        if main_sk not in main_floats:
            main_floats[main_sk] = _draw_float(float_min, float_max)
        for part in row.accessories:
            acc_sk = (scope, part.float_key)
            if acc_sk not in accessory_floats:
                accessory_floats[acc_sk] = _draw_float(float_min, float_max)

    out: dict[int, tuple[float, float, float]] = {}
    for row in rows:
        main_sk = (scope, row.main_key)
        main_float = main_floats.get(main_sk, 0.0)
        accessory_float_sum = round(
            sum(accessory_floats.get((scope, part.float_key), 0.0) for part in row.accessories),
            2,
        )
        group_price = round(
            row.main_price + main_float + row.accessory_cost_sum + accessory_float_sum,
            2,
        )
        group_price = clamp_accessory_cost_group_price(
            group_price,
            main_price=row.main_price,
            accessory_cost_sum=row.accessory_cost_sum,
        )
        out[row.sku_index] = (main_float, accessory_float_sum, group_price)
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
    """上架单元内所有 SKU 按主/配件分别浮动重算拼单价。"""
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
        accessory_costs: list[float] = []
        for code in accessory_codes:
            accessory_costs.append(
                lookup_accessory_cost(code, cost_map=cost_map, catalog=catalog)
            )
        main_price = round(float(entry.price or 0.0), 2)
        rows.append(
            _SkuPricingRow(
                sku_index=index,
                main_key=main_float_key(catalog, main_code, main_price),
                main_price=main_price,
                accessories=tuple(
                    accessory_float_key_for_codes(accessory_codes, costs=accessory_costs)
                ),
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
        _, _, group_price = reconciled[row.sku_index]
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

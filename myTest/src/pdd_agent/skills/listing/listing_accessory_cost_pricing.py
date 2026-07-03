"""配件成本定价模式（整合链路可选）。

开启后拼单价 = 主商品「拼多多定价+5元」 + 主商品浮动(0~5) + Σ(配件聚水潭成本 + 配件浮动(0~5))。
主商品：规格图文件名首段 / 单款时的款式码（来自飞书「拼多多定价+5元」列）。
子商品：组合里的配件码，或套装文件名 + 段中除首段外的所有段（来自飞书「聚水潭ERP商品列表」成本）。

浮动规则（listing_accessory_cost_float_registry）：
- 主商品：同族且上架定价相同 → 共享主浮动（如 BD014A/C 同价）；
- 配件：同配件族且聚水潭成本相同 → 共享配件浮动（如 YKL001A/B 成本都是 1.5）；
- 成本或定价不同 → 各自独立随机浮动；不再强制跨款式组合同价。
"""

from __future__ import annotations

import random
from contextvars import ContextVar
from typing import Any

from pdd_agent.integrations.feishu.config import FeishuConfig, accessory_cost_pricing_enabled, load_feishu_config
from pdd_agent.skills.listing.listing_accessory_cost_float_registry import (
    accessory_float_key,
    accessory_float_key_for_codes,
    apply_reconciled_prices_to_unit,
    clamp_accessory_cost_group_price,
    main_float_key,
    reconcile_accessory_cost_floats,
)
from pdd_agent.skills.listing.pdd_product_catalog import (
    BUNDLE_MODEL_CODE,
    ComboPricingError,
    PddProductEntry,
    _format_price,
    _norm_code,
    catalog_codes_match,
    find_catalog_entry,
    resolve_listing_price_scope,
)

if True:
    from pdd_agent.domain.models import ListingUnit

_active_ctx: ContextVar[bool] = ContextVar("accessory_cost_pricing_active", default=False)
_cost_map_ctx: ContextVar[dict[str, float]] = ContextVar("accessory_cost_pricing_cost_map", default={})
_float_min_ctx: ContextVar[float] = ContextVar("accessory_cost_pricing_float_min", default=0.0)
_float_max_ctx: ContextVar[float] = ContextVar("accessory_cost_pricing_float_max", default=5.0)
_main_float_ctx: ContextVar[dict[tuple[str, str], float]] = ContextVar(
    "accessory_cost_pricing_main_float",
    default={},
)
_accessory_float_ctx: ContextVar[dict[tuple[str, str], float]] = ContextVar(
    "accessory_cost_pricing_accessory_float",
    default={},
)


def is_accessory_cost_pricing_active() -> bool:
    return bool(_active_ctx.get())


def ensure_accessory_cost_pricing_active() -> bool:
    """配置开启且尚未激活时，懒加载聚水潭成本表（预检/上架均可调用）。"""
    if is_accessory_cost_pricing_active():
        return True
    if not accessory_cost_pricing_enabled():
        return False
    cfg = load_feishu_config()
    from pdd_agent.integrations.feishu.jushuitan_erp_inventory import load_jushuitan_cost_map

    pipe = cfg.pipeline
    activate_accessory_cost_pricing(
        cost_map=load_jushuitan_cost_map(config=cfg),
        float_min=pipe.accessory_cost_float_min,
        float_max=pipe.accessory_cost_float_max,
    )
    return True


def activate_accessory_cost_pricing(
    *,
    cost_map: dict[str, float] | None = None,
    float_min: float = 0.0,
    float_max: float = 5.0,
) -> None:
    """上架任务开始前激活（通常由 task_runner 调用）。"""
    _active_ctx.set(True)
    _cost_map_ctx.set(dict(cost_map or {}))
    _float_min_ctx.set(max(0.0, float(float_min)))
    _float_max_ctx.set(max(_float_min_ctx.get(), float(float_max)))
    _main_float_ctx.set({})
    _accessory_float_ctx.set({})


def deactivate_accessory_cost_pricing() -> None:
    _active_ctx.set(False)
    _cost_map_ctx.set({})
    _main_float_ctx.set({})
    _accessory_float_ctx.set({})


def accessory_cost_pricing_config(cfg: FeishuConfig | None = None) -> dict[str, Any]:
    active = cfg or load_feishu_config()
    pipe = active.pipeline
    return {
        "enabled": accessory_cost_pricing_enabled(active),
        "float_min": float(pipe.accessory_cost_float_min),
        "float_max": float(pipe.accessory_cost_float_max),
    }


def split_main_and_accessory_codes(
    *,
    style_code: str,
    model_code: str,
    bundle_components: list[str] | None = None,
) -> tuple[str, list[str]]:
    """主商品码 + 子商品码列表（子商品可为空）。"""
    style = str(style_code or "").strip()
    model = str(model_code or "").strip()
    if not style:
        return "", []
    if catalog_codes_match(model, style):
        return style, []
    if _norm_code(model) == BUNDLE_MODEL_CODE and bundle_components:
        parts = [str(code).strip() for code in bundle_components if str(code).strip()]
        if not parts:
            return style, []
        return parts[0], parts[1:]
    if model and not catalog_codes_match(model, style):
        return style, [model]
    return style, []


def _lookup_accessory_cost(
    code: str,
    *,
    cost_map: dict[str, float],
    catalog: dict[str, PddProductEntry],
) -> float:
    norm = _norm_code(code)
    if norm in cost_map:
        return round(float(cost_map[norm]), 2)
    entry = find_catalog_entry(catalog, code)
    if entry is not None:
        canonical = _norm_code(entry.code)
        if canonical in cost_map:
            return round(float(cost_map[canonical]), 2)
    raise ComboPricingError(missing_codes=[code], reason="jushuitan_cost_missing")


def _require_main_entry(code: str, catalog: dict[str, PddProductEntry]) -> PddProductEntry:
    entry = find_catalog_entry(catalog, code)
    if not entry:
        raise ComboPricingError(missing_codes=[code], reason="catalog_code_missing")
    if float(entry.price or 0.0) <= 0:
        raise ComboPricingError(invalid_codes=[code], reason="pricing_invalid")
    return entry


def _resolve_main_float(*, listing_scope: str, main_key: str) -> float:
    scope = str(listing_scope or "").strip() or "__default__"
    main_sk = (scope, main_key)
    main_floats = dict(_main_float_ctx.get())
    if main_sk not in main_floats:
        main_floats[main_sk] = round(
            random.uniform(_float_min_ctx.get(), _float_max_ctx.get()),
            2,
        )
        _main_float_ctx.set(main_floats)
    return main_floats[main_sk]


def _resolve_accessory_floats(
    *,
    listing_scope: str,
    accessory_codes: list[str],
    accessory_costs: list[float],
) -> float:
    scope = str(listing_scope or "").strip() or "__default__"
    accessory_floats = dict(_accessory_float_ctx.get())
    total = 0.0
    for code, cost in zip(accessory_codes, accessory_costs):
        key = accessory_float_key(code, cost)
        acc_sk = (scope, key)
        if acc_sk not in accessory_floats:
            accessory_floats[acc_sk] = round(
                random.uniform(_float_min_ctx.get(), _float_max_ctx.get()),
                2,
            )
        total += accessory_floats[acc_sk]
    _accessory_float_ctx.set(accessory_floats)
    return round(total, 2)


def _resolve_float_delta(
    *,
    listing_scope: str,
    catalog: dict[str, PddProductEntry],
    main_code: str,
    main_price: float,
    accessory_codes: list[str],
    accessory_cost_sum: float,
) -> float:
    """增量定价：主浮动 + 配件浮动之和（单元 reconcile 后会再次统一校正）。"""
    _ = accessory_cost_sum
    main_key = main_float_key(catalog, main_code, main_price)
    main_float = _resolve_main_float(listing_scope=listing_scope, main_key=main_key)
    cost_map = _cost_map_ctx.get()
    accessory_costs = [
        _lookup_accessory_cost(code, cost_map=cost_map, catalog=catalog)
        for code in accessory_codes
    ]
    accessory_float_sum = _resolve_accessory_floats(
        listing_scope=listing_scope,
        accessory_codes=accessory_codes,
        accessory_costs=accessory_costs,
    )
    return round(main_float + accessory_float_sum, 2)


def _resolve_inventory(
    *,
    main_entry: PddProductEntry,
    accessory_codes: list[str],
    catalog: dict[str, PddProductEntry],
    bundle_components: list[str] | None,
    model_code: str,
    fallback_inv: str = "10",
) -> str:
    if _norm_code(model_code) == BUNDLE_MODEL_CODE and bundle_components:
        codes = [_norm_code(code) for code in bundle_components if _norm_code(code)]
        inventories: list[int] = []
        for code in codes:
            entry = find_catalog_entry(catalog, code)
            if entry:
                inventories.append(int(entry.inventory or 0))
        return str(min(inventories) if inventories else fallback_inv)

    if accessory_codes:
        inventories = [int(main_entry.inventory or 0)]
        for code in accessory_codes:
            entry = find_catalog_entry(catalog, code)
            if entry:
                inventories.append(int(entry.inventory or 0))
        return str(min(inventories) if inventories else fallback_inv)

    return str(main_entry.inventory if main_entry.inventory is not None else fallback_inv)


def resolve_accessory_cost_pricing(
    style_code: str,
    model_code: str,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
    *,
    listing_scope: str = "",
    bundle_components: list[str] | None = None,
) -> tuple[str, str, str]:
    """配件成本模式拼单价：主商品定价 + 子商品成本 + 继承浮动。"""
    _ = defaults
    cost_map = _cost_map_ctx.get()
    main_code, accessory_codes = split_main_and_accessory_codes(
        style_code=style_code,
        model_code=model_code,
        bundle_components=bundle_components,
    )
    if not main_code:
        raise ComboPricingError(missing_codes=[style_code], reason="catalog_code_missing")

    main_entry = _require_main_entry(main_code, catalog)
    main_price = round(float(main_entry.price or 0.0), 2)

    accessory_cost_sum = 0.0
    for code in accessory_codes:
        accessory_cost_sum += _lookup_accessory_cost(code, cost_map=cost_map, catalog=catalog)

    float_delta = _resolve_float_delta(
        listing_scope=listing_scope,
        catalog=catalog,
        main_code=main_code,
        main_price=main_price,
        accessory_codes=accessory_codes,
        accessory_cost_sum=accessory_cost_sum,
    )
    group_price = round(main_price + accessory_cost_sum + float_delta, 2)

    group_price = clamp_accessory_cost_group_price(
        group_price,
        main_price=main_price,
        accessory_cost_sum=accessory_cost_sum,
    )

    if group_price <= 0:
        raise ComboPricingError(invalid_codes=[main_entry.code], reason="pricing_invalid")

    from pdd_agent.skills.listing.listing_price_float import get_listing_price_float_registry

    single_price = get_listing_price_float_registry().effective_single_price(listing_scope, group_price)
    inventory = _resolve_inventory(
        main_entry=main_entry,
        accessory_codes=accessory_codes,
        catalog=catalog,
        bundle_components=bundle_components,
        model_code=model_code,
    )
    return inventory, _format_price(group_price), _format_price(single_price)


def reconcile_accessory_cost_prices_for_unit(
    unit: ListingUnit,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
) -> None:
    """上架单元解析完成后，按主/配件分别浮动重算全部 SKU 拼单价。"""
    _ = defaults
    if not ensure_accessory_cost_pricing_active() or not unit.skus:
        return

    from pdd_agent.skills.listing.catalog import _parse_combo_component_codes
    from pdd_agent.skills.listing.listing_price_float import get_listing_price_float_registry

    listing_scope = resolve_listing_price_scope(
        family_code=unit.family_code,
        image_set=unit.image_set,
        listing_label=unit.listing_label,
    )
    registry = get_listing_price_float_registry()

    apply_reconciled_prices_to_unit(
        unit,
        catalog,
        listing_scope=listing_scope,
        float_min=_float_min_ctx.get(),
        float_max=_float_max_ctx.get(),
        cost_map=_cost_map_ctx.get(),
        lookup_accessory_cost=_lookup_accessory_cost,
        split_main_and_accessory_codes=split_main_and_accessory_codes,
        bundle_model_code=BUNDLE_MODEL_CODE,
        parse_combo_component_codes=_parse_combo_component_codes,
        resolve_inventory=_resolve_inventory,
        format_price=_format_price,
        effective_single_price=registry.effective_single_price,
    )


def resolve_sku_pricing_with_accessory_cost_if_enabled(
    *,
    style_code: str,
    model_code: str,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
    listing_scope: str = "",
    bundle_components: list[str] | None = None,
) -> tuple[str, str, str] | None:
    """已开启配件成本模式时返回 (库存, 拼单价, 单买价)，否则 None。"""
    if not ensure_accessory_cost_pricing_active():
        return None
    return resolve_accessory_cost_pricing(
        style_code,
        model_code,
        catalog,
        defaults,
        listing_scope=listing_scope,
        bundle_components=bundle_components,
    )


__all__ = [
    "accessory_cost_pricing_config",
    "activate_accessory_cost_pricing",
    "deactivate_accessory_cost_pricing",
    "ensure_accessory_cost_pricing_active",
    "is_accessory_cost_pricing_active",
    "reconcile_accessory_cost_floats",
    "reconcile_accessory_cost_prices_for_unit",
    "resolve_accessory_cost_pricing",
    "resolve_sku_pricing_with_accessory_cost_if_enabled",
    "split_main_and_accessory_codes",
]

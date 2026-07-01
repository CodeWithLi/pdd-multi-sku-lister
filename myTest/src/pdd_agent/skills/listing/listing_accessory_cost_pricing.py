"""配件成本定价模式（整合链路可选）。

开启后拼单价 = 主商品拼多多定价 + Σ(子商品聚水潭成本) + 一次 0~5 元浮动。
主商品：规格图文件名首段 / 单款时的款式码（来自飞书「拼多多比价定价」）。
子商品：组合里的配件码，或套装文件名 + 段中除首段外的所有段（来自飞书「聚水潭ERP商品列表」成本）。

本模块独立封装，关闭开关后原有 resolve_combo_pricing 逻辑不变。
"""

from __future__ import annotations

import random
from contextvars import ContextVar
from typing import Any

from pdd_agent.integrations.feishu.config import FeishuConfig, accessory_cost_pricing_enabled, load_feishu_config
from pdd_agent.skills.listing.pdd_product_catalog import (
    BUNDLE_MODEL_CODE,
    ComboPricingError,
    PddProductEntry,
    _format_price,
    _norm_code,
    catalog_codes_match,
    find_catalog_entry,
)

_active_ctx: ContextVar[bool] = ContextVar("accessory_cost_pricing_active", default=False)
_cost_map_ctx: ContextVar[dict[str, float]] = ContextVar("accessory_cost_pricing_cost_map", default={})
_float_min_ctx: ContextVar[float] = ContextVar("accessory_cost_pricing_float_min", default=0.0)
_float_max_ctx: ContextVar[float] = ContextVar("accessory_cost_pricing_float_max", default=5.0)
_float_cache_ctx: ContextVar[dict[tuple[str, str], float]] = ContextVar(
    "accessory_cost_pricing_float_cache",
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
    _float_cache_ctx.set({})


def deactivate_accessory_cost_pricing() -> None:
    _active_ctx.set(False)
    _cost_map_ctx.set({})
    _float_cache_ctx.set({})


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


def _sku_float_key(listing_scope: str, style_code: str, model_code: str, accessory_codes: list[str]) -> tuple[str, str]:
    scope = str(listing_scope or "").strip() or "__default__"
    accessory_sig = "+".join(_norm_code(code) for code in accessory_codes)
    model_sig = _norm_code(model_code) or style_code
    return scope, f"{_norm_code(style_code)}|{model_sig}|{accessory_sig}"


def _final_float_delta(listing_scope: str, style_code: str, model_code: str, accessory_codes: list[str]) -> float:
    key = _sku_float_key(listing_scope, style_code, model_code, accessory_codes)
    cache = dict(_float_cache_ctx.get())
    if key not in cache:
        cache[key] = round(random.uniform(_float_min_ctx.get(), _float_max_ctx.get()), 2)
        _float_cache_ctx.set(cache)
    return cache[key]


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
    """配件成本模式拼单价：主商品定价 + 子商品成本 + 一次浮动。"""
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

    float_delta = _final_float_delta(listing_scope, style_code, model_code, accessory_codes)
    group_price = round(main_price + accessory_cost_sum + float_delta, 2)
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

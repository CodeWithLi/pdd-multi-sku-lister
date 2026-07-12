"""配件成本定价 / 子商品档位浮动 — 第一步后接入。"""

from __future__ import annotations

from dy_agent.domain.models import ListingUnit
from dy_agent.skills.listing.listing_options import ListingOptions


def apply_accessory_pricing_if_enabled(unit: ListingUnit, options: ListingOptions) -> dict:
    """预留：根据开关计算配件成本价与档位浮动。"""
    return {
        "accessory_cost_pricing": options.accessory_cost_pricing,
        "accessory_tiered_float": options.accessory_tiered_float,
        "ready": False,
        "note": "pricing_pending",
        "merchant_code": unit.merchant_code,
    }


def resolve_accessory_prices(
    unit: ListingUnit,
    options: ListingOptions,
    defaults: dict[str, str] | None = None,
) -> dict[str, str]:
    """占位：后续从飞书/配置表读取配件成本并计算售价。"""
    if not options.accessory_cost_pricing and not options.accessory_tiered_float:
        return dict(defaults or {})
    raise NotImplementedError(
        f"[{unit.listing_label}] 配件成本定价/档位浮动尚未实现"
    )

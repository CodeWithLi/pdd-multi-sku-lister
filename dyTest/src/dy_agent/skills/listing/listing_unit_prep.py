"""上架前单元预处理：主款优先、飞书定价、规格开关校验。"""

from __future__ import annotations

from dy_agent.core.config import load_yaml_settings
from dy_agent.domain.models import ListingUnit
from dy_agent.integrations.feishu.config import accessory_cost_pricing_enabled, load_feishu_config
from dy_agent.skills.listing.catalog import load_product_catalog
from dy_agent.skills.listing.listing_accessory_cost_pricing import (
    ensure_accessory_cost_pricing_active,
    reconcile_accessory_cost_prices_for_unit,
)
from dy_agent.skills.listing.listing_options import ListingOptions
from dy_agent.skills.listing.listing_primary_style_first import apply_primary_style_first_to_unit


def prepare_listing_unit(
    unit: ListingUnit,
    options: ListingOptions,
    *,
    account_id: str = "",
) -> dict:
    """浏览器填表前预处理 ListingUnit，返回各开关执行摘要。"""
    summary: dict = {
        "primary_style_first": None,
        "spec_fill_verify_test": options.spec_fill_verify_test,
        "accessory_cost_pricing": options.accessory_cost_pricing,
        "accessory_tiered_float": options.accessory_tiered_float,
    }

    if options.primary_style_first_test:
        summary["primary_style_first"] = apply_primary_style_first_to_unit(
            unit,
            account_id=account_id,
            enabled=True,
        )

    pending: list[str] = []
    if options.spec_fill_verify_test:
        summary["spec_fill_verify"] = "enabled"

    use_pricing = options.accessory_cost_pricing or accessory_cost_pricing_enabled(load_feishu_config())
    if use_pricing:
        if ensure_accessory_cost_pricing_active():
            settings = load_yaml_settings()
            catalog = load_product_catalog(settings)
            reconcile_accessory_cost_prices_for_unit(
                unit,
                catalog,
                settings.multi_spec.defaults,
            )
            summary["accessory_cost_pricing_applied"] = True
        else:
            pending.append("配件成本定价（飞书/聚水潭加载失败）")
    elif options.accessory_cost_pricing:
        pending.append("配件成本定价（飞书配置未开启）")

    if options.accessory_tiered_float and not summary.get("accessory_cost_pricing_applied"):
        pending.append("配件阶梯浮动（需先开启配件成本定价）")

    if pending:
        summary["pending_features"] = pending

    return summary

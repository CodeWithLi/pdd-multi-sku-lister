"""上架任务飞书上下文初始化（与 PDD 共用表/token）。"""

from __future__ import annotations

from dy_agent.core.logging import get_logger
from dy_agent.integrations.feishu.config import (
    accessory_cost_pricing_enabled,
    accessory_cost_tiered_float_enabled,
    load_feishu_config,
)
from dy_agent.integrations.feishu.listing_feishu_snapshot import init_listing_feishu_snapshot
from dy_agent.skills.listing.listing_accessory_cost_pricing import (
    activate_accessory_cost_pricing,
    deactivate_accessory_cost_pricing,
)
from dy_agent.skills.listing.listing_price_float import reset_listing_price_float_registry

logger = get_logger(__name__)


def bootstrap_listing_feishu(
    *,
    accessory_cost_pricing: bool = False,
    accessory_tiered_float: bool = False,
) -> dict:
    """初始化上架飞书快照与定价浮动上下文。"""
    init_listing_feishu_snapshot()
    summary: dict = {"snapshot": True}

    try:
        cfg = load_feishu_config()
        use_pricing = accessory_cost_pricing_enabled(cfg) or accessory_cost_pricing
        use_tiered = accessory_cost_tiered_float_enabled(cfg) or accessory_tiered_float
        cat_cfg = cfg.pdd_product_catalog

        if use_pricing:
            from dy_agent.integrations.feishu.jushuitan_erp_inventory import load_jushuitan_cost_map

            pipe_cfg = cfg.pipeline
            activate_accessory_cost_pricing(
                cost_map=load_jushuitan_cost_map(config=cfg),
                float_min=pipe_cfg.accessory_cost_float_min,
                float_max=pipe_cfg.accessory_cost_float_max,
                tiered_float_enabled=use_tiered,
            )
            reset_listing_price_float_registry(
                enabled=False,
                single_float_min=cat_cfg.single_price_float_min,
                single_float_max=cat_cfg.single_price_float_max,
            )
            summary["accessory_cost_pricing"] = True
            summary["accessory_tiered_float"] = use_tiered
        else:
            deactivate_accessory_cost_pricing()
            reset_listing_price_float_registry(
                float_min=cat_cfg.price_float_min,
                float_max=cat_cfg.price_float_max,
                enabled=cat_cfg.price_float_enabled,
                single_float_min=cat_cfg.single_price_float_min,
                single_float_max=cat_cfg.single_price_float_max,
            )
            summary["accessory_cost_pricing"] = False
    except Exception:
        logger.exception("bootstrap listing feishu failed")
        summary["error"] = "bootstrap_failed"

    return summary

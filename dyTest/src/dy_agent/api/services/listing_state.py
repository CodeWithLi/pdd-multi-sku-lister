"""从 settings / API 请求构建 listing 图状态片段。"""

from __future__ import annotations

from dy_agent.api.schemas.tasks import ListingTaskRequest
from dy_agent.core.config import ListingConfig, YamlSettings


def listing_flags_from_request(body: ListingTaskRequest, listing_cfg: ListingConfig) -> dict:
    def _pick(name: str, default: bool) -> bool:
        value = getattr(body, name, None)
        return default if value is None else bool(value)

    return {
        "slot_alignment_test": _pick("slot_alignment_test", listing_cfg.slot_alignment_test),
        "spec_fill_verify_test": _pick("spec_fill_verify_test", listing_cfg.spec_fill_verify_test),
        "primary_style_first_test": _pick(
            "primary_style_first_test", listing_cfg.primary_style_first_test
        ),
        "category_next_burst_demo": _pick(
            "category_next_burst_demo", listing_cfg.category_next_burst_demo
        ),
        "accessory_cost_pricing": _pick("accessory_cost_pricing", listing_cfg.accessory_cost_pricing),
        "accessory_tiered_float": _pick("accessory_tiered_float", listing_cfg.accessory_tiered_float),
    }


def listing_flags_from_settings(settings: YamlSettings) -> dict:
    cfg = settings.listing
    return {
        "slot_alignment_test": cfg.slot_alignment_test,
        "spec_fill_verify_test": cfg.spec_fill_verify_test,
        "primary_style_first_test": cfg.primary_style_first_test,
        "category_next_burst_demo": cfg.category_next_burst_demo,
        "accessory_cost_pricing": cfg.accessory_cost_pricing,
        "accessory_tiered_float": cfg.accessory_tiered_float,
    }

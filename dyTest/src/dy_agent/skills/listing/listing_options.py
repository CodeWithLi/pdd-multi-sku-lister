"""上架流程开关（与拼多多 pipeline 对齐，供后续步骤接入）。"""

from __future__ import annotations

from dataclasses import dataclass

from dy_agent.core.config import YamlSettings


@dataclass(frozen=True)
class ListingOptions:
    slot_alignment_test: bool = False
    spec_fill_verify_test: bool = True
    primary_style_first_test: bool = True
    category_next_burst_demo: bool = True
    accessory_cost_pricing: bool = True
    accessory_tiered_float: bool = True
    title_mode: str = "page_ai"
    category_keyword: str = ""
    brand_name: str = "无品牌"
    manufacturer_name: str = ""


def listing_options_from_settings(settings: YamlSettings, *, category_keyword: str = "") -> ListingOptions:
    listing = settings.listing
    return ListingOptions(
        slot_alignment_test=listing.slot_alignment_test,
        spec_fill_verify_test=listing.spec_fill_verify_test,
        primary_style_first_test=listing.primary_style_first_test,
        category_next_burst_demo=listing.category_next_burst_demo,
        accessory_cost_pricing=listing.accessory_cost_pricing,
        accessory_tiered_float=listing.accessory_tiered_float,
        title_mode=str(listing.title_mode or "page_ai"),
        category_keyword=category_keyword or str(listing.category_keyword or ""),
        brand_name=str(listing.brand_name or "无品牌"),
        manufacturer_name=str(listing.manufacturer_name or ""),
    )

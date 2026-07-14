"""类目属性填写单元测试（无 Playwright）。"""

from __future__ import annotations

from dy_agent.skills.listing.listing_options import ListingOptions, listing_options_from_settings
from dy_agent.core.config import ListingConfig, YamlSettings


def test_listing_options_include_category_attrs():
    opts = ListingOptions(brand_name="无品牌", manufacturer_name="义乌某某厂")
    assert opts.brand_name == "无品牌"
    assert opts.manufacturer_name == "义乌某某厂"


def test_listing_options_from_settings_reads_attrs():
    settings = YamlSettings(
        listing=ListingConfig(
            brand_name="无品牌",
            manufacturer_name="测试厂家",
        )
    )
    opts = listing_options_from_settings(settings)
    assert opts.brand_name == "无品牌"
    assert opts.manufacturer_name == "测试厂家"

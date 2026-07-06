"""Tests for listing product attribute seed and repository."""

from pdd_agent.domain.listing_product_attributes import DEFAULT_LISTING_PRODUCT_ATTRIBUTES


def test_default_listing_product_attributes_seed():
    keys = {item.field_key for item in DEFAULT_LISTING_PRODUCT_ATTRIBUTES}
    assert "brand" in keys
    assert "transparent" in keys
    assert "has_layer" in keys
    assert "product_type" in keys

    disabled = {item.field_key for item in DEFAULT_LISTING_PRODUCT_ATTRIBUTES if not item.enabled}
    assert disabled == {"transparent", "has_layer", "product_type"}

    brand = next(item for item in DEFAULT_LISTING_PRODUCT_ATTRIBUTES if item.field_key == "brand")
    assert brand.selected_value == "无品牌/无注册商标"
    assert brand.label == "品牌"

    packaging = next(item for item in DEFAULT_LISTING_PRODUCT_ATTRIBUTES if item.field_key == "packaging")
    assert packaging.selected_value == "简装"

    enabled_count = sum(1 for item in DEFAULT_LISTING_PRODUCT_ATTRIBUTES if item.enabled)
    assert enabled_count == 13

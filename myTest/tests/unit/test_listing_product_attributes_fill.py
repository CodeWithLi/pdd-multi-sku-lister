"""Tests for listing product attributes fill helpers."""

from pdd_agent.domain.listing_product_attributes import DEFAULT_LISTING_PRODUCT_ATTRIBUTES
from pdd_agent.skills.listing.listing_product_attributes_fill import (
    NO_RESULT_PHRASES,
    _norm_text,
    load_enabled_listing_product_attributes,
)


def test_norm_text_strips_spaces():
    assert _norm_text("无品牌/无注册商标") == "无品牌/无注册商标"
    assert _norm_text("重 要 材质") == "重要材质"


def test_load_enabled_listing_product_attributes_fallback(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.db.session.is_database_available",
        lambda: False,
    )
    items = load_enabled_listing_product_attributes()
    assert items
    keys = {item["field_key"] for item in items}
    assert "brand" in keys
    assert "transparent" not in keys
    assert "has_layer" not in keys
    assert "product_type" not in keys
    assert len(items) == sum(1 for x in DEFAULT_LISTING_PRODUCT_ATTRIBUTES if x.enabled and x.selected_value)


def test_no_result_phrases_contains_search_empty():
    assert "搜索无结果" in NO_RESULT_PHRASES

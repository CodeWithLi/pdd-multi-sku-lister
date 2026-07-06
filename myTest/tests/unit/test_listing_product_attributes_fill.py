"""Tests for listing product attributes fill helpers."""

from pdd_agent.domain.listing_product_attributes import DEFAULT_LISTING_PRODUCT_ATTRIBUTES
from pdd_agent.skills.listing.listing_product_attributes_fill import (
    LOG_TAG,
    NO_RESULT_PHRASES,
    REASON_CODES,
    _dropdown_options_match_field,
    _is_skip_option_text,
    _norm_text,
    _option_matches,
    _reason_code,
    _row_matches_label,
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


def test_row_matches_label():
    assert _row_matches_label("品牌\n请选择", "品牌")
    assert _row_matches_label("重要\n材质\n请选择", "重要材质")
    assert not _row_matches_label("流行元素\n请选择", "特点")


def test_option_matches_partial():
    assert _option_matches("无品牌/无注册商标", "无品牌/无注册商标")
    assert _option_matches("帆布", "帆布")
    assert not _option_matches("帆布客", "帆布")


def test_skip_more_brand_hint():
    assert _is_skip_option_text("更多品牌请搜索")
    assert not _is_skip_option_text("无品牌/无注册商标")


def test_reason_code_mapping():
    assert _reason_code("not_found") == "ATTR_INPUT_NOT_FOUND"
    assert _reason_code("timeout") == "ATTR_DROPDOWN_TIMEOUT"
    assert REASON_CODES["section_not_ready"] == "ATTR_SECTION_NOT_READY"


def test_dropdown_options_match_field():
    brand_opts = ["无品牌/无注册商标", "Pepsi/百事"]
    assert _dropdown_options_match_field(brand_opts, "品牌")
    assert not _dropdown_options_match_field(brand_opts, "重要材质")
    assert _dropdown_options_match_field(["帆布", "PU"], "重要材质")


def test_log_tag_constant():
    assert LOG_TAG == "product_attrs"

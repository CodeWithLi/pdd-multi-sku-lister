"""pdd_spec_format 单元测试。"""

from __future__ import annotations

from pdd_agent.skills.published.pdd_spec_format import (
    build_spec_combined,
    enrich_sku_spec_fields,
    listing_sku_spec_fields,
    parse_spec_text,
)
from pdd_agent.skills.published.pdd_sku_normalize import normalize_pdd_lookup_sku


def test_parse_spec_text_style_and_taocan():
    parsed = parse_spec_text(
        "款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】 当前价：¥12.80"
    )
    assert parsed["dim1_key"] == "款式"
    assert parsed["dim1_value"] == "蓝色慕斯星星笔袋"
    assert parsed["dim2_key"] == "套餐"
    assert parsed["dim2_value"] == "单件装：包包【爆款热销】"
    assert parsed["spec_count"] == 2
    assert parsed["spec_combined"] == (
        "款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】"
    )


def test_parse_spec_text_style_and_chicun():
    parsed = parse_spec_text(
        "款式: 透明小丑鱼笔袋；尺寸: 灰鲨鱼头套-KT猫挂件 当前价：¥60.00"
    )
    assert parsed["dim1_key"] == "款式"
    assert parsed["dim2_key"] == "尺寸"
    assert parsed["spec_count"] == 2


def test_parse_spec_text_single_spec():
    parsed = parse_spec_text("款式: 纯色帆布袋")
    assert parsed["spec_count"] == 1
    assert parsed["dim2_value"] == ""
    assert parsed["spec_combined"] == "款式: 纯色帆布袋"


def test_listing_sku_spec_fields_dual_and_single():
    dual = listing_sku_spec_fields(
        style_name="蓝色慕斯星星笔袋",
        model_name="两件套：包包+挂件",
    )
    assert dual["spec_count"] == 2
    assert dual["spec_dim2_key"] == "尺寸"
    assert dual["spec_combined"] == "款式: 蓝色慕斯星星笔袋；套餐: 两件套：包包+挂件"
    assert "尺寸:" in dual["spec_combined_listing"]

    single = listing_sku_spec_fields(style_name="纯色帆布袋", model_name="")
    assert single["spec_count"] == 1
    assert single["spec_combined"] == "款式: 纯色帆布袋"


def test_normalize_pdd_lookup_sku_includes_spec_dims():
    sku = normalize_pdd_lookup_sku(
        {
            "style_name": "蓝色慕斯星星笔袋",
            "package_name": "单件装：包包【爆款热销】",
            "spec_code": "BD630D",
            "spec_dim1_key": "款式",
            "spec_dim2_key": "套餐",
            "group_price": "12.80",
        }
    )
    assert sku["spec_dim1_key"] == "款式"
    assert sku["spec_dim2_key"] == "套餐"
    assert sku["spec_combined"] == (
        "款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】"
    )


def test_enrich_sku_from_scrape_headers():
    fields = enrich_sku_spec_fields(
        {
            "style_name": "蓝色清新笔袋",
            "package_name": "两件套：包包+挂件",
            "spec_dim1_key": "款式",
            "spec_dim2_key": "套餐",
            "spec_count": 2,
        }
    )
    assert fields["spec_combined"] == build_spec_combined(
        "款式", "蓝色清新笔袋", "套餐", "两件套：包包+挂件"
    )

from types import SimpleNamespace

from pdd_agent.skills.campaign.activity_price_validate import (
    _group_products_for_filter,
    _match_spec_to_sku,
    _normalize_spec_name,
    _parse_page_spec,
    _resolve_price_floor,
    validate_spec_prices,
)
from pdd_agent.skills.campaign.price_rules import CodePriceEntry, find_code_by_label


def _published_row(
    *,
    pdd_product_id: str = "965527041720",
    product_code: str = "BD046A",
    skus: list[dict] | None = None,
):
    return SimpleNamespace(
        mapping_id="m1",
        pdd_product_id=pdd_product_id,
        product_code=product_code,
        spec_metadata={"skus": skus or []},
    )


def test_normalize_spec_name_strips_prefix_and_color():
    assert _normalize_spec_name("款式: 透明小丑鱼笔袋 (主图款式) - 白") == "透明小丑鱼笔袋"


def test_match_parent_spec_to_single_sku():
    skus = [
        {
            "style_code": "BD046A",
            "style_name": "透明小丑鱼笔袋",
            "model_code": "BD046A",
            "model_name": "透明小丑鱼笔袋",
            "combo_folder": "BD046A",
        }
    ]
    matched = _match_spec_to_sku("款式: 透明小丑鱼笔袋 (主图款式) - 白", skus)
    assert matched is not None
    assert matched["style_code"] == "BD046A"


def test_match_combo_spec_to_combo_sku():
    skus = [
        {
            "style_code": "BD046A",
            "style_name": "透明小丑鱼笔袋",
            "model_code": "AXBD001A",
            "model_name": "米白色爱心笔袋",
            "combo_folder": "BD046A+AXBD001A",
        }
    ]
    matched = _match_spec_to_sku("款式: 透明小丑鱼笔袋 + 米白色爱心笔袋 - 白", skus)
    assert matched is not None
    assert matched["combo_folder"] == "BD046A+AXBD001A"


def test_resolve_price_floor_parent_only():
    sku = {
        "style_code": "BD014C",
        "model_code": "BD014C",
        "combo_folder": "BD014C",
    }
    floor_info = _resolve_price_floor(
        sku=sku,
        product_code="BD014C",
        pricing_map={"BD014C": 7.0},
        control_map={"AXBD001A": 2.0},
    )
    assert floor_info["is_combo"] is False
    assert floor_info["floor_price"] == 7.0


def test_resolve_price_floor_combo_uses_pricing_plus_control():
    sku = {
        "style_code": "BD046A",
        "model_code": "AXBD001A",
        "combo_folder": "BD046A+AXBD001A",
    }
    floor_info = _resolve_price_floor(
        sku=sku,
        product_code="BD046A",
        pricing_map={"BD046A": 10.0},
        control_map={"AXBD001A": 2.5},
    )
    assert floor_info["is_combo"] is True
    assert floor_info["floor_price"] == 12.5


def test_validate_spec_prices_passes_when_activity_price_above_floor():
    row = _published_row(
        skus=[
            {
                "style_code": "BD014C",
                "style_name": "印花KT笔袋",
                "model_code": "BD014C",
                "model_name": "印花KT笔袋",
                "combo_folder": "BD014C",
            }
        ]
    )
    result = validate_spec_prices(
        specs=[{"spec_name": "款式: 印花KT笔袋 (主图款式) - 白", "activity_price": "8.5"}],
        published_rows=[row],
        pricing_map={"BD014C": 7.0},
        control_map={},
    )
    assert result["status"] == "success"
    assert result["passed_count"] == 1


def test_parse_page_spec_supports_style_and_size_format():
    parsed = _parse_page_spec(
        "款式: 透明小丑鱼笔袋；尺寸: 灰鲨鱼头套-KT猫挂件 当前价：¥60.00 线上库存：999"
    )
    assert parsed["style_text"] == "透明小丑鱼笔袋"
    assert parsed["size_text"] == "灰鲨鱼头套-KT猫挂件"
    assert parsed["is_combo"] is True


def test_find_code_by_label_matches_control_name_suffix():
    entries = [
        CodePriceEntry(raw_code="YKL001A灰鲨鱼头套", norm_code="YKL001A", label="灰鲨鱼头套", price=2.5),
    ]
    assert find_code_by_label(entries, "灰鲨鱼头套-KT猫挂件") == "YKL001A"


def test_validate_spec_prices_uses_product_code_when_db_skus_empty():
    row = _published_row(product_code="BD046A", skus=[])
    shark_label = "\u7070\u9ca8\u9c7c\u5934\u5957"
    spec_name = (
        "\u6b3e\u5f0f: \u900f\u660e\u5c0f\u4e11\u9c7c\u7b14\u888b\uff1b\u5c3a\u5bf8: "
        f"{shark_label}-KT\u732b\u6302\u4ef6 \u5f53\u524d\u4ef7\uff1a\xa560.00 \u7ebf\u4e0a\u5e93\u5b58\uff1a999"
    )
    result = validate_spec_prices(
        specs=[{"spec_name": spec_name, "activity_price": "49.8"}],
        published_rows=[row],
        pricing_map={"BD046A": 10.0},
        control_map={"YKL001A": 2.5},
        control_entries=[
            CodePriceEntry(
                raw_code=f"YKL001A{shark_label}",
                norm_code="YKL001A",
                label=shark_label,
                price=2.5,
            ),
        ],
    )
    assert result["status"] == "success"
    assert result["results"][0]["parent_code"] == "BD046A"
    assert result["results"][0]["child_code"] == "YKL001A"


def test_group_products_for_filter_removes_product_when_any_spec_invalid():
    results = [
        {"pdd_product_id": "111", "should_remove": False, "valid": True},
        {"pdd_product_id": "111", "should_remove": True, "valid": False},
        {"pdd_product_id": "222", "should_remove": False, "valid": True},
    ]
    kept, removed = _group_products_for_filter(results)
    assert kept == ["222"]
    assert removed == ["111"]


def test_validate_spec_prices_marks_skipped_specs_for_removal():
    row = _published_row(product_code="BD046A", skus=[])
    shark_label = "\u7070\u9ca8\u9c7c\u5934\u5957"
    spec_name = (
        "\u6b3e\u5f0f: \u900f\u660e\u5c0f\u4e11\u9c7c\u7b14\u888b\uff1b\u5c3a\u5bf8: "
        f"{shark_label}-KT\u732b\u6302\u4ef6"
    )
    result = validate_spec_prices(
        specs=[{"spec_name": spec_name, "activity_price": "49.8"}],
        published_rows=[row],
        pricing_map={},
        control_map={},
        control_entries=[],
    )
    assert result["remove_count"] == 1
    assert result["results"][0]["should_remove"] is True


def test_validate_spec_prices_skips_when_pricing_missing():
    row = _published_row(product_code="BD046A", skus=[])
    shark_label = "\u7070\u9ca8\u9c7c\u5934\u5957"
    spec_name = (
        "\u6b3e\u5f0f: \u900f\u660e\u5c0f\u4e11\u9c7c\u7b14\u888b\uff1b\u5c3a\u5bf8: "
        f"{shark_label}-KT\u732b\u6302\u4ef6"
    )
    result = validate_spec_prices(
        specs=[{"spec_name": spec_name, "activity_price": "49.8"}],
        published_rows=[row],
        pricing_map={},
        control_map={},
        control_entries=[],
    )
    assert result["status"] == "success"
    assert result["skipped_count"] == 1
    assert result["results"][0]["reason"] == "skipped_child_code_not_found"


def test_validate_spec_prices_fails_when_activity_price_below_floor():
    row = _published_row(
        skus=[
            {
                "style_code": "BD046A",
                "style_name": "透明小丑鱼笔袋",
                "model_code": "AXBD001A",
                "model_name": "米白色爱心笔袋",
                "combo_folder": "BD046A+AXBD001A",
            }
        ]
    )
    result = validate_spec_prices(
        specs=[{"spec_name": "款式: 透明小丑鱼笔袋 + 米白色爱心笔袋 - 白", "activity_price": "11.0"}],
        published_rows=[row],
        pricing_map={"BD046A": 10.0},
        control_map={"AXBD001A": 2.5},
    )
    assert result["status"] == "failed"
    assert result["failed_count"] == 1
    assert result["results"][0]["reason"] == "activity_price_not_above_floor"

from types import SimpleNamespace

from pdd_agent.skills.campaign.activity_price_validate import (
    _build_removed_spec_record,
    _delete_invalid_price_goods,
    _extract_spec_name_from_tooltip_text,
    _format_removal_reason_text,
    _group_products_for_filter,
    _is_truncated_spec_text,
    _match_spec_to_sku,
    _normalize_spec_name,
    _parse_page_spec,
    _resolve_price_floor,
    _row_matches_spec_target,
    _spec_row_match_keys,
    filter_price_confirm_page,
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


def test_format_removal_reason_text_for_low_price():
    text = _format_removal_reason_text(
        "activity_price_not_above_floor",
        {
            "activity_price": 8.8,
            "floor_price": 9.42,
            "parent_code": "BD630D",
            "child_code": "YKL020A",
            "pricing": 8.42,
            "control_price": 1.0,
        },
    )
    assert "活动价 8.8" in text
    assert "底价 9.42" in text
    assert "母码 BD630D" in text
    assert "子码 YKL020A" in text


def test_validate_spec_prices_exposes_removed_specs_summary():
    row = _published_row(product_code="BD630D", skus=[])
    row.spec_metadata = {
        "pdd_goods_lookup": {
            "pdd_skus": [
                {
                    "style_name": "单件装：包包【爆款热销】",
                    "package_name": "预览",
                    "spec_code": "BD630D",
                }
            ]
        }
    }
    result = validate_spec_prices(
        specs=[
            {
                "spec_name": "款式: 蓝色；套餐: 单件装：包包【爆款热销】",
                "activity_price": "7.0",
            }
        ],
        published_rows=[row],
        pricing_map={"BD630D": 8.42},
        control_map={},
    )
    assert result["remove_count"] == 1
    assert len(result["removed_specs"]) == 1
    removed = result["removed_specs"][0]
    assert removed["spec_code"] == "BD630D"
    assert removed["reason"] == "activity_price_not_above_floor"
    assert "活动价 7.0" in removed["reason_text"]


def test_build_removed_spec_record_marks_delete_failure():
    record = _build_removed_spec_record(
        {
            "spec_name": "款式: A",
            "spec_code": "BD630D",
            "activity_price": 7.0,
            "floor_price": 8.42,
            "parent_code": "BD630D",
            "pricing": 8.42,
            "reason": "activity_price_not_above_floor",
        },
        deleted=False,
        delete_error="delete_goods_not_found",
    )
    assert record["deleted"] is False
    assert record["delete_error"] == "delete_goods_not_found"
    assert record["delete_error_text"] == "活动页未找到删除按钮"


def test_group_products_for_filter_only_removes_when_all_specs_invalid():
    results = [
        {"pdd_product_id": "111", "should_remove": False, "valid": True},
        {"pdd_product_id": "111", "should_remove": True, "valid": False},
        {"pdd_product_id": "222", "should_remove": False, "valid": True},
        {"pdd_product_id": "333", "should_remove": True, "valid": False},
        {"pdd_product_id": "333", "should_remove": True, "valid": False},
    ]
    kept, removed, partial = _group_products_for_filter(results)
    assert kept == ["111", "222"]
    assert removed == ["333"]
    assert partial == ["111"]


def test_spec_row_match_keys_prefers_package_fragment():
    spec_name = "款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】"
    keys = _spec_row_match_keys(spec_name)
    assert "单件装：包包【爆款热销】" in keys


def test_row_matches_spec_target_uses_activity_price():
    row_text = "款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】 活动价 8.8 删除"
    assert _row_matches_spec_target(
        row_text,
        product_id="",
        spec_name="款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】",
        activity_price="8.8",
    )
    assert not _row_matches_spec_target(
        row_text,
        product_id="",
        spec_name="款式: 蓝色慕斯星星笔袋；套餐: 两件套：包包+挂件",
        activity_price="9.8",
    )


def test_delete_invalid_price_goods_deletes_each_invalid_spec(monkeypatch):
    page = SimpleNamespace(url="https://mms.pinduoduo.com/act/goods_price/confirm")
    calls: list[dict[str, str]] = []

    def fake_delete(_page, *, product_id="", spec_name="", activity_price=""):
        calls.append(
            {
                "product_id": product_id,
                "spec_name": spec_name,
                "activity_price": activity_price,
            }
        )
        return {"deleted": True, "method": "mock"}

    monkeypatch.setattr(
        "pdd_agent.skills.campaign.activity_price_validate._delete_price_confirm_goods",
        fake_delete,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.activity_price_validate._on_price_confirm_page",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.activity_price_validate._scrape_price_confirm_specs",
        lambda *_args, **_kwargs: {"spec_count": 1, "specs": [{"spec_name": "ok", "activity_price": "9.8"}]},
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.activity_price_validate._read_price_confirm_empty_state",
        lambda *_args, **_kwargs: {"empty": False},
    )

    validation = {
        "results": [
            {
                "pdd_product_id": "111",
                "spec_name": "款式: A；套餐: 单件",
                "activity_price": "8.8",
                "should_remove": True,
            },
            {
                "pdd_product_id": "111",
                "spec_name": "款式: A；套餐: 两件套",
                "activity_price": "9.8",
                "should_remove": False,
            },
            {
                "pdd_product_id": "222",
                "spec_name": "款式: B；套餐: 单件",
                "activity_price": "7.8",
                "should_remove": True,
            },
        ]
    }
    result = _delete_invalid_price_goods(page, "store_A", validation)
    assert len(calls) == 2
    assert calls[0]["activity_price"] == "8.8"
    assert calls[1]["activity_price"] == "7.8"
    assert result["deleted_spec_count"] == 2
    assert result["remaining_count"] == 1
    assert len(result["removed_specs"]) == 2
    assert result["removed_specs"][0]["reason_text"]
    assert result["removed_specs"][0]["deleted"] is True


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


def test_parse_page_spec_supports_guige_separator():
    parsed = _parse_page_spec("款式：蓝色慕斯星星笔袋套装；规格：单件装：包包【爆款热销】 当前价 ¥12.80")
    assert parsed["style_text"] == "蓝色慕斯星星笔袋套装"
    assert parsed["size_text"] == "单件装：包包【爆款热销】"
    assert parsed["is_combo"] is False


def test_parse_page_spec_supports_taocan_separator():
    parsed = _parse_page_spec("款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】 当前价：¥12.80")
    assert parsed["style_text"] == "蓝色慕斯星星笔袋"
    assert parsed["size_text"] == "单件装：包包【爆款热销】"
    assert parsed["is_combo"] is False


def test_is_truncated_spec_text_detects_ellipsis():
    assert _is_truncated_spec_text("款式: 蓝色；套餐: 单件装...") is True
    assert _is_truncated_spec_text("款式: 蓝色；套餐: 单件装：包包【爆款热销】") is False


def test_extract_spec_name_from_tooltip_text():
    tooltip = (
        "款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】\n"
        "当前价: ¥12.80\n"
        "线上库存: 298"
    )
    assert _extract_spec_name_from_tooltip_text(tooltip) == (
        "款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】"
    )


def test_validate_danjian_package_matches_single_sku_and_passes_floor():
    from pdd_agent.skills.campaign.activity_price_validate import _match_spec_to_pdd_sku

    skus = [
        {
            "style_name": "单件装：包包【爆款热销】",
            "package_name": "预览",
            "spec_code": "BD630D",
        },
        {
            "style_name": "两件套：包包+挂件",
            "package_name": "预览",
            "spec_code": "BD630D+YKL001A",
        },
    ]
    spec_name = "款式: 蓝色慕斯星星笔袋；套餐: 单件装：包包【爆款热销】"
    matched, score, method = _match_spec_to_pdd_sku(spec_name, skus)
    assert matched is not None
    assert matched["spec_code"] == "BD630D"
    assert method == "pdd_single_package"

    row = _published_row(
        pdd_product_id="965180544666",
        product_code="965180544666",
        skus=[],
    )
    row.spec_metadata = {"pdd_goods_lookup": {"pdd_skus": skus}}
    result = validate_spec_prices(
        specs=[{"spec_name": spec_name, "activity_price": "8.8"}],
        published_rows=[row],
        pricing_map={"BD630D": 8.42},
        control_map={},
    )
    assert result["results"][0]["valid"] is True
    assert result["results"][0]["should_remove"] is False
    assert result["results"][0]["spec_code"] == "BD630D"


def test_lookup_spec_codes_from_pdd_lookup_skus():
    from pdd_agent.skills.campaign.activity_price_validate import lookup_spec_codes_from_specs

    row = _published_row(
        pdd_product_id="965182969751",
        product_code="BD716C",
        skus=[],
    )
    row.spec_metadata = {
        "pdd_goods_lookup": {
            "pdd_skus": [
                {
                    "style_name": "单件装：包包【爆款热销】",
                    "package_name": "预览",
                    "spec_code": "BD716B+YKL001AC",
                    "group_price": "13.8",
                }
            ]
        }
    }
    result = lookup_spec_codes_from_specs(
        specs=[
            {
                "spec_name": "款式：蓝色慕斯星星笔袋套装；规格：单件装：包包【爆款热销】",
                "activity_price": "8.8",
                "product_id": "965182969751",
            }
        ],
        published_rows=[row],
    )
    assert result["status"] == "success"
    assert result["matched_count"] == 1
    assert result["rows"][0]["spec_code"] == "BD716B+YKL001AC"
    assert result["rows"][0]["activity_price"] == "8.8"


def test_validate_spec_prices_uses_pdd_lookup_skus_for_manual_product():
    row = _published_row(
        pdd_product_id="965182969751",
        product_code="BD716C",
        skus=[],
    )
    row.spec_metadata = {
        "pdd_goods_lookup": {
            "pdd_skus": [
                {
                    "style_name": "单件装：包包【爆款热销】",
                    "package_name": "预览",
                    "spec_code": "BD716B+YKL001AC",
                    "group_price": "13.8",
                }
            ]
        }
    }
    result = validate_spec_prices(
        specs=[
            {
                "spec_name": "款式：蓝色慕斯星星笔袋套装；规格：单件装：包包【爆款热销】",
                "activity_price": "8.8",
                "product_id": "965182969751",
            }
        ],
        published_rows=[row],
        pricing_map={"BD716B": 7.0},
        control_map={"YKL001AC": 1.5},
    )
    assert result["results"][0]["sku_matched"] is True
    assert result["results"][0]["spec_code"] == "BD716B+YKL001AC"
    assert result["results"][0]["match_method"] == "pdd_lookup_text"
    assert result["results"][0]["floor_price"] == 8.5
    assert result["results"][0]["valid"] is True


def test_filter_price_confirm_page_all_removed_status_not_overwritten(monkeypatch):
    page = SimpleNamespace(url="https://mms.pinduoduo.com/act/goods_price/confirm")
    state = {
        "status": "success",
        "step": "price_validation_ready",
        "validation": {"remove_count": 2, "spec_count": 2},
    }
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.activity_price_validate._prepare_price_validation_state",
        lambda *_args, **_kwargs: state,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.activity_price_validate._delete_invalid_price_goods",
        lambda *_args, **_kwargs: {
            "remaining_count": 0,
            "empty_state": {"empty": True},
            "on_price_confirm_after": True,
        },
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.activity_price_validate._close_price_confirm_page",
        lambda *_args, **_kwargs: {"closed": True, "method": "close_tab"},
    )
    result = filter_price_confirm_page(page, "store_A", ["111"])
    assert result["status"] == "all_products_removed"
    assert result["action"] == "close_page"

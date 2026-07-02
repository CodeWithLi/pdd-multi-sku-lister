"""配件成本定价 — 浮动继承与同配件同价。"""

from __future__ import annotations

import pytest

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.listing_accessory_cost_float_registry import (
    _SkuPricingRow,
    combo_align_key,
    reconcile_accessory_cost_floats,
)
from pdd_agent.skills.listing.listing_accessory_cost_pricing import (
    activate_accessory_cost_pricing,
    deactivate_accessory_cost_pricing,
    reconcile_accessory_cost_prices_for_unit,
    resolve_accessory_cost_pricing,
    resolve_sku_pricing_with_accessory_cost_if_enabled,
    split_main_and_accessory_codes,
)
from pdd_agent.skills.listing.listing_price_float import reset_listing_price_float_registry
from pdd_agent.skills.listing.pdd_product_catalog import (
    BUNDLE_MODEL_CODE,
    ComboPricingError,
    PddProductEntry,
    product_code_family_key,
)


@pytest.fixture(autouse=True)
def _reset_accessory_cost_context():
    deactivate_accessory_cost_pricing()
    reset_listing_price_float_registry(enabled=False, single_float_min=0.0, single_float_max=0.0)
    yield
    deactivate_accessory_cost_pricing()


def test_split_main_and_accessory_codes():
    assert split_main_and_accessory_codes(style_code="BD716A", model_code="BD716A") == ("BD716A", [])
    assert split_main_and_accessory_codes(style_code="BD716A", model_code="YKL001N") == (
        "BD716A",
        ["YKL001N"],
    )
    assert split_main_and_accessory_codes(
        style_code="BD032D",
        model_code=BUNDLE_MODEL_CODE,
        bundle_components=["BD032D", "YKL020A", "YKL004L"],
    ) == ("BD032D", ["YKL020A", "YKL004L"])


def test_product_code_family_key_strips_trailing_variant_letter():
    assert product_code_family_key("BD037A") == "BD037"
    assert product_code_family_key("BD037B") == "BD037"
    assert product_code_family_key("BD037A奶油泡芙笔袋") == "BD037"
    assert product_code_family_key("YKL001N") == "YKL001"
    assert product_code_family_key("YKL001P") == "YKL001"
    assert product_code_family_key("YKL123A") == "YKL123"
    assert product_code_family_key("YKL989A") == "YKL989"


def test_combo_align_key_matches_variant_colors():
    catalog = {
        "BD046A": PddProductEntry("BD046A", "A", "笔袋", 100, 18.0),
        "BD046B": PddProductEntry("BD046B", "B", "笔袋", 100, 16.0),
    }
    assert combo_align_key("BD046A", ["YKL001A"], catalog) == "BD046|YKL001"
    assert combo_align_key("BD046B", ["YKL001P"], catalog) == "BD046|YKL001"
    assert combo_align_key("BD046A", ["YKL001N", "YKL008A"], catalog) == "BD046|YKL001+YKL008"
    assert combo_align_key("BD046B", ["YKL001P", "YKL008B"], catalog) == "BD046|YKL001+YKL008"
    assert combo_align_key("BD046A", ["YKL123A", "YKL008A"], catalog) == "BD046|YKL008+YKL123"
    assert combo_align_key("BD046B", ["YKL989A", "YKL008A"], catalog) == "BD046|YKL008+YKL989"
    assert combo_align_key("BD046A", ["YKL123A", "YKL008A"], catalog) != combo_align_key(
        "BD046B", ["YKL989A", "YKL008A"], catalog
    )


def test_main_group_inherits_float_across_solo_combo_bundle():
    rows = [
        _SkuPricingRow(0, "BD037", 10.0, 0.0, "", False),
        _SkuPricingRow(1, "BD037", 10.0, 2.0, "BD037|YKL001", True),
        _SkuPricingRow(2, "BD037", 10.0, 7.0, "", True),
    ]
    result = reconcile_accessory_cost_floats(rows, listing_scope="BD037/第一套图", float_min=3.0, float_max=3.0)
    assert result[0][0] == 3.0
    assert result[0][1] == 13.0
    assert result[1][1] == 15.0
    assert result[2][0] == 3.0
    assert result[2][1] == 20.0


def test_shared_accessory_combo_price_across_mains():
    rows = [
        _SkuPricingRow(0, "BD037", 10.0, 0.0, "", False),
        _SkuPricingRow(1, "BD037", 10.0, 2.0, "BD037|YKL001", True),
        _SkuPricingRow(2, "BD037", 8.0, 0.0, "", False),
        _SkuPricingRow(3, "BD037", 8.0, 2.0, "BD037|YKL001", True),
        _SkuPricingRow(4, "BD037", 9.0, 0.0, "", False),
        _SkuPricingRow(5, "BD037", 9.0, 1.5, "BD037|YKL001", True),
    ]
    result = reconcile_accessory_cost_floats(rows, listing_scope="BD037/第一套图", float_min=3.0, float_max=3.0)
    assert result[1][1] == 15.0
    assert result[3][1] == 15.0
    assert result[5][1] == 15.0
    assert result[3][0] == 4.5
    assert result[2][1] == 12.5
    assert result[0][1] == 14.5


def test_resolve_accessory_cost_pricing_combo_uses_main_price_and_accessory_cost():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 20.0),
        "YKL001N": PddProductEntry("YKL001N", "挂架", "亚克力", 50, 5.0),
    }
    activate_accessory_cost_pricing(
        cost_map={"YKL001N": 1.2},
        float_min=2.0,
        float_max=2.0,
    )
    inv, gp, sp = resolve_accessory_cost_pricing(
        "BD716A",
        "YKL001N",
        catalog,
        {},
        listing_scope="BD716/第一套图",
    )
    assert inv == "50"
    assert gp == "23.2"
    assert sp == "23.2"


def test_reconcile_accessory_cost_prices_for_unit_updates_skus():
    catalog = {
        "BD037A": PddProductEntry("BD037A", "A笔袋", "笔袋", 100, 10.0),
        "BD037B": PddProductEntry("BD037B", "B笔袋", "笔袋", 100, 8.0),
        "YKL001A": PddProductEntry("YKL001A", "配件", "亚克力", 50, 5.0),
    }
    activate_accessory_cost_pricing(cost_map={"YKL001A": 2.0}, float_min=3.0, float_max=3.0)
    unit = ListingUnit(
        product_code="BD037A",
        family_code="BD037",
        image_set="第一套图",
        root=__import__("pathlib").Path("."),
        skus=[
            SkuCombo(
                style_code="BD037A",
                style_name="",
                model_code="BD037A",
                model_name="",
                combo_folder="BD037A",
                preview_image=__import__("pathlib").Path("a.png"),
                group_price="0",
                single_price="0",
            ),
            SkuCombo(
                style_code="BD037A",
                style_name="",
                model_code="YKL001A",
                model_name="",
                combo_folder="BD037A+YKL001A",
                preview_image=__import__("pathlib").Path("b.png"),
                group_price="0",
                single_price="0",
            ),
            SkuCombo(
                style_code="BD037B",
                style_name="",
                model_code="BD037B",
                model_name="",
                combo_folder="BD037B",
                preview_image=__import__("pathlib").Path("c.png"),
                group_price="0",
                single_price="0",
            ),
            SkuCombo(
                style_code="BD037B",
                style_name="",
                model_code="YKL001A",
                model_name="",
                combo_folder="BD037B+YKL001A",
                preview_image=__import__("pathlib").Path("d.png"),
                group_price="0",
                single_price="0",
            ),
        ],
    )
    reconcile_accessory_cost_prices_for_unit(unit, catalog, {})
    assert unit.skus[0].group_price == "15"
    assert unit.skus[1].group_price == "15"
    assert unit.skus[2].group_price == "13"
    assert unit.skus[3].group_price == "15"


def test_resolve_accessory_cost_pricing_missing_cost_raises():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 20.0),
        "YKL001N": PddProductEntry("YKL001N", "挂架", "亚克力", 50, 5.0),
    }
    activate_accessory_cost_pricing(cost_map={}, float_min=0.0, float_max=0.0)
    with pytest.raises(ComboPricingError) as exc:
        resolve_accessory_cost_pricing("BD716A", "YKL001N", catalog, {})
    assert exc.value.reason == "jushuitan_cost_missing"


def test_resolve_sku_pricing_with_accessory_cost_if_enabled_returns_none_when_inactive(monkeypatch):
    catalog = {"BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 10.0)}
    monkeypatch.setattr(
        "pdd_agent.skills.listing.listing_accessory_cost_pricing.accessory_cost_pricing_enabled",
        lambda cfg=None: False,
    )
    deactivate_accessory_cost_pricing()
    assert (
        resolve_sku_pricing_with_accessory_cost_if_enabled(
            style_code="BD716A",
            model_code="BD716A",
            catalog=catalog,
            defaults={},
        )
        is None
    )


def test_bd046_ab_family_shares_float_and_ykl001_aligns():
    """BD046A/B 主商品族共享浮动；YKL001N/P 单配件对齐；YKL123/YKL989 套餐不对齐。"""
    catalog = {
        "BD046A": PddProductEntry("BD046A", "A款", "笔袋", 100, 18.0),
        "BD046B": PddProductEntry("BD046B", "B款", "笔袋", 100, 16.0),
        "YKL001N": PddProductEntry("YKL001N", "挂架N", "亚克力", 50, 5.0),
        "YKL001P": PddProductEntry("YKL001P", "挂架P", "亚克力", 50, 5.0),
        "YKL008A": PddProductEntry("YKL008A", "配件8A", "亚克力", 50, 5.0),
        "YKL008B": PddProductEntry("YKL008B", "配件8B", "亚克力", 50, 5.0),
        "YKL123A": PddProductEntry("YKL123A", "配件123", "亚克力", 50, 5.0),
        "YKL989A": PddProductEntry("YKL989A", "配件989", "亚克力", 50, 5.0),
    }
    cost_map = {
        "YKL001N": 1.5,
        "YKL001P": 1.5,
        "YKL008A": 2.0,
        "YKL008B": 2.0,
        "YKL123A": 3.0,
        "YKL989A": 4.0,
    }
    activate_accessory_cost_pricing(cost_map=cost_map, float_min=3.0, float_max=3.0)
    unit = ListingUnit(
        product_code="BD046A",
        family_code="BD046",
        image_set="第一套",
        root=__import__("pathlib").Path("."),
        skus=[
            SkuCombo(
                style_code="BD046A",
                style_name="",
                model_code="BD046A",
                model_name="",
                combo_folder="BD046A",
                preview_image=__import__("pathlib").Path("a.png"),
            ),
            SkuCombo(
                style_code="BD046A",
                style_name="",
                model_code="YKL001N",
                model_name="",
                combo_folder="BD046A+YKL001N",
                preview_image=__import__("pathlib").Path("b.png"),
            ),
            SkuCombo(
                style_code="BD046A",
                style_name="",
                model_code=BUNDLE_MODEL_CODE,
                model_name="",
                combo_folder="BD046A+YKL001N+YKL008A",
                preview_image=__import__("pathlib").Path("c.png"),
            ),
            SkuCombo(
                style_code="BD046A",
                style_name="",
                model_code=BUNDLE_MODEL_CODE,
                model_name="",
                combo_folder="BD046A+YKL123A+YKL008A",
                preview_image=__import__("pathlib").Path("d.png"),
            ),
            SkuCombo(
                style_code="BD046B",
                style_name="",
                model_code="BD046B",
                model_name="",
                combo_folder="BD046B",
                preview_image=__import__("pathlib").Path("e.png"),
            ),
            SkuCombo(
                style_code="BD046B",
                style_name="",
                model_code="YKL001P",
                model_name="",
                combo_folder="BD046B+YKL001P",
                preview_image=__import__("pathlib").Path("f.png"),
            ),
            SkuCombo(
                style_code="BD046B",
                style_name="",
                model_code=BUNDLE_MODEL_CODE,
                model_name="",
                combo_folder="BD046B+YKL001P+YKL008B",
                preview_image=__import__("pathlib").Path("g.png"),
            ),
            SkuCombo(
                style_code="BD046B",
                style_name="",
                model_code=BUNDLE_MODEL_CODE,
                model_name="",
                combo_folder="BD046B+YKL989A+YKL008A",
                preview_image=__import__("pathlib").Path("h.png"),
            ),
        ],
    )
    reconcile_accessory_cost_prices_for_unit(unit, catalog, {})

    by_folder = {sku.combo_folder: sku.group_price for sku in unit.skus}
    assert by_folder["BD046A+YKL001N"] == by_folder["BD046B+YKL001P"] == "22.5"
    assert by_folder["BD046A+YKL001N+YKL008A"] == by_folder["BD046B+YKL001P+YKL008B"]
    assert by_folder["BD046A"] == "23"
    assert by_folder["BD046B"] == "21"
    assert float(by_folder["BD046A+YKL123A+YKL008A"]) != float(
        by_folder["BD046B+YKL989A+YKL008A"]
    )

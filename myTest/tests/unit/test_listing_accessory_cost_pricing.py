"""配件成本定价 — 主/配件分别浮动。"""

from __future__ import annotations

import pytest

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.listing_accessory_cost_float_registry import (
    _AccessoryCostPart,
    _SkuPricingRow,
    accessory_cost_group_price_floor,
    accessory_float_key,
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
    assert product_code_family_key("YKL001N") == "YKL001"
    assert product_code_family_key("YKL001P") == "YKL001"


def test_accessory_float_key_shares_only_when_cost_matches():
    assert accessory_float_key("YKL001A", 1.5) == accessory_float_key("YKL001B", 1.5) == "YKL001@1.50"
    assert accessory_float_key("YKL001A", 1.2) != accessory_float_key("YKL001B", 1.8)


def test_main_and_accessory_floats_are_independent():
    rows = [
        _SkuPricingRow(0, "BD037@10.00", 10.0, (), False),
        _SkuPricingRow(
            1,
            "BD037@10.00",
            10.0,
            (_AccessoryCostPart(accessory_float_key("YKL001N", 2.0), 2.0),),
            True,
        ),
    ]
    result = reconcile_accessory_cost_floats(rows, listing_scope="BD037/套1", float_min=3.0, float_max=3.0)
    assert result[0][2] == 13.0
    assert result[1][2] == 18.0


def test_accessory_float_inherited_for_same_family_and_cost():
    rows = [
        _SkuPricingRow(
            0,
            "BD014@10.00",
            10.0,
            (_AccessoryCostPart(accessory_float_key("YKL001A", 1.5), 1.5),),
            True,
        ),
        _SkuPricingRow(
            1,
            "BD014@10.00",
            10.0,
            (_AccessoryCostPart(accessory_float_key("YKL001B", 1.5), 1.5),),
            True,
        ),
        _SkuPricingRow(
            2,
            "BD014@10.00",
            10.0,
            (_AccessoryCostPart(accessory_float_key("YKL001C", 2.0), 2.0),),
            True,
        ),
    ]
    result = reconcile_accessory_cost_floats(rows, listing_scope="BD014/套1", float_min=2.0, float_max=2.0)
    assert result[0][1] == result[1][1] == 2.0
    assert result[0][2] == result[1][2] == 15.5
    assert result[2][2] == 16.0


def test_accessory_float_differs_when_cost_differs_even_if_same_family():
    rows = [
        _SkuPricingRow(
            0,
            "BD014@10.00",
            10.0,
            (_AccessoryCostPart(accessory_float_key("YKL001A", 1.2), 1.2),),
            True,
        ),
        _SkuPricingRow(
            1,
            "BD014@10.00",
            10.0,
            (_AccessoryCostPart(accessory_float_key("YKL001B", 1.8), 1.8),),
            True,
        ),
    ]
    result = reconcile_accessory_cost_floats(rows, listing_scope="BD014/套1", float_min=0.2, float_max=0.2)
    assert result[0][2] == 11.6
    assert result[1][2] == 12.2
    assert result[0][2] != result[1][2]


def test_resolve_accessory_cost_pricing_uses_separate_main_and_accessory_floats():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 13.6),
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
    assert gp == "18.8"
    assert sp == "18.8"


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
    assert unit.skus[0].group_price == "13"
    assert unit.skus[1].group_price == "18"
    assert unit.skus[2].group_price == "11"
    assert unit.skus[3].group_price == "16"


def test_resolve_accessory_cost_pricing_missing_cost_raises():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 20.0),
        "YKL001N": PddProductEntry("YKL001N", "挂架", "亚克力", 50, 5.0),
    }
    activate_accessory_cost_pricing(cost_map={}, float_min=0.0, float_max=0.0)
    with pytest.raises(ComboPricingError) as exc:
        resolve_accessory_cost_pricing("BD716A", "YKL001N", catalog, {})
    assert exc.value.reason == "bundle_pricing_missing"


def test_resolve_sku_pricing_with_accessory_cost_if_enabled_returns_none_when_inactive(monkeypatch):
    catalog = {"BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 10.0)}
    monkeypatch.setattr(
        "pdd_agent.skills.listing.listing_accessory_cost_pricing.accessory_style_pricing_enabled",
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


def test_resolve_accessory_cost_pricing_original_sum_no_float():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 10.0),
    }
    activate_accessory_cost_pricing(cost_map={"YKL001A": 2.0}, original_sum=True)
    inv, gp, sp = resolve_accessory_cost_pricing("BD716A", "YKL001A", catalog, {})
    assert inv == "100"
    assert gp == "12"
    assert float(sp) >= float(gp)
    deactivate_accessory_cost_pricing()


def test_solo_sku_not_below_main_price():
    main = 8.6
    rows = [
        _SkuPricingRow(0, "BD113@8.60", main, (), False),
        _SkuPricingRow(
            1,
            "BD113@8.60",
            main,
            (_AccessoryCostPart(accessory_float_key("ACC", 1.0), 1.0),),
            True,
        ),
    ]
    result = reconcile_accessory_cost_floats(rows, listing_scope="BD113/套1", float_min=1.04, float_max=1.04)
    assert result[0][2] >= main
    assert result[0][2] == round(main + 1.04, 2)


def test_group_price_floor_never_below_main_catalog_price():
    import random

    main = 8.6
    base_rows = [
        _SkuPricingRow(0, "BD113@8.60", main, (), False),
        _SkuPricingRow(
            1,
            "BD113@8.60",
            main,
            (_AccessoryCostPart(accessory_float_key("ACC", 1.0), 1.0),),
            True,
        ),
        _SkuPricingRow(
            2,
            "BD113@8.60",
            main,
            (_AccessoryCostPart(accessory_float_key("ACC2", 6.3), 6.3),),
            True,
        ),
    ]
    for seed in range(50):
        random.seed(seed)
        order = list(base_rows)
        random.shuffle(order)
        result = reconcile_accessory_cost_floats(order, listing_scope="BD113/套1", float_min=0.0, float_max=5.0)
        for row in order:
            price = result[row.sku_index][2]
            floor = accessory_cost_group_price_floor(row.main_price, row.accessory_cost_sum)
            assert price >= floor >= row.main_price


def test_bd014_same_main_price_shares_main_float_not_forced_combo_align():
    catalog = {
        "BD014A": PddProductEntry("BD014A", "A款", "笔袋", 100, 10.0),
        "BD014B": PddProductEntry("BD014B", "B款", "笔袋", 100, 8.0),
        "BD014C": PddProductEntry("BD014C", "C款", "笔袋", 100, 10.0),
        "YKL001AC": PddProductEntry("YKL001AC", "配件", "亚克力", 50, 5.0),
    }
    activate_accessory_cost_pricing(cost_map={"YKL001AC": 2.0}, float_min=3.0, float_max=3.0)
    unit = ListingUnit(
        product_code="BD014A",
        family_code="BD014",
        image_set="第一套",
        root=__import__("pathlib").Path("."),
        skus=[
            SkuCombo(
                style_code="BD014A",
                style_name="",
                model_code="YKL001AC",
                model_name="",
                combo_folder="BD014A+YKL001AC",
                preview_image=__import__("pathlib").Path("a.png"),
            ),
            SkuCombo(
                style_code="BD014B",
                style_name="",
                model_code="YKL001AC",
                model_name="",
                combo_folder="BD014B+YKL001AC",
                preview_image=__import__("pathlib").Path("b.png"),
            ),
            SkuCombo(
                style_code="BD014C",
                style_name="",
                model_code="YKL001AC",
                model_name="",
                combo_folder="BD014C+YKL001AC",
                preview_image=__import__("pathlib").Path("c.png"),
            ),
        ],
    )
    reconcile_accessory_cost_prices_for_unit(unit, catalog, {})
    by_folder = {sku.combo_folder: sku.group_price for sku in unit.skus}
    assert by_folder["BD014A+YKL001AC"] == by_folder["BD014C+YKL001AC"] == "18"
    assert by_folder["BD014B+YKL001AC"] == "16"


def test_bd014_ab_combo_not_forced_same_when_accessory_cost_differs():
    catalog = {
        "BD014A": PddProductEntry("BD014A", "A款", "笔袋", 100, 10.0),
        "BD014B": PddProductEntry("BD014B", "B款", "笔袋", 100, 10.0),
        "YKL001A": PddProductEntry("YKL001A", "配件A", "亚克力", 50, 5.0),
        "YKL001B": PddProductEntry("YKL001B", "配件B", "亚克力", 50, 5.0),
    }
    activate_accessory_cost_pricing(
        cost_map={"YKL001A": 1.2, "YKL001B": 1.8},
        float_min=0.2,
        float_max=0.2,
    )
    unit = ListingUnit(
        product_code="BD014A",
        family_code="BD014",
        image_set="第一套",
        root=__import__("pathlib").Path("."),
        skus=[
            SkuCombo(
                style_code="BD014A",
                style_name="",
                model_code="YKL001A",
                model_name="",
                combo_folder="BD014A+YKL001A",
                preview_image=__import__("pathlib").Path("a.png"),
            ),
            SkuCombo(
                style_code="BD014B",
                style_name="",
                model_code="YKL001B",
                model_name="",
                combo_folder="BD014B+YKL001B",
                preview_image=__import__("pathlib").Path("b.png"),
            ),
        ],
    )
    reconcile_accessory_cost_prices_for_unit(unit, catalog, {})
    by_folder = {sku.combo_folder: sku.group_price for sku in unit.skus}
    assert by_folder["BD014A+YKL001A"] == "11.6"
    assert by_folder["BD014B+YKL001B"] == "12.2"
    assert by_folder["BD014A+YKL001A"] != by_folder["BD014B+YKL001B"]

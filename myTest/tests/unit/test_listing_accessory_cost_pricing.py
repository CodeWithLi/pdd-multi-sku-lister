"""配件成本定价 — 浮动继承与同配件同价。"""

from __future__ import annotations

import pytest

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.listing_accessory_cost_float_registry import (
    _SkuPricingRow,
    accessory_align_key,
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


def test_accessory_align_key_only_single_accessory():
    assert accessory_align_key(["YKL001A"]) == "YKL001A"
    assert accessory_align_key(["YKL001A", "YKL020A"]) == ""


def test_main_group_inherits_float_across_solo_combo_bundle():
    rows = [
        _SkuPricingRow(0, "BD037A", 10.0, 0.0, "", False),
        _SkuPricingRow(1, "BD037A", 10.0, 2.0, "YKL001A", True),
        _SkuPricingRow(2, "BD037A", 10.0, 7.0, "", True),
    ]
    result = reconcile_accessory_cost_floats(rows, listing_scope="BD037/第一套图", float_min=3.0, float_max=3.0)
    assert result[0][0] == 3.0
    assert result[0][1] == 13.0
    assert result[1][1] == 15.0
    assert result[2][0] == 3.0
    assert result[2][1] == 20.0


def test_shared_accessory_combo_price_across_mains():
    rows = [
        _SkuPricingRow(0, "BD037A", 10.0, 0.0, "", False),
        _SkuPricingRow(1, "BD037A", 10.0, 2.0, "YKL001A", True),
        _SkuPricingRow(2, "BD037B", 8.0, 0.0, "", False),
        _SkuPricingRow(3, "BD037B", 8.0, 2.0, "YKL001A", True),
        _SkuPricingRow(4, "BD037C", 9.0, 0.0, "", False),
        _SkuPricingRow(5, "BD037C", 9.0, 1.5, "YKL001P", True),
    ]
    result = reconcile_accessory_cost_floats(rows, listing_scope="BD037/第一套图", float_min=3.0, float_max=3.0)
    assert result[1][1] == 15.0
    assert result[3][1] == 15.0
    assert result[3][0] == 5.0
    assert result[2][1] == 13.0
    assert result[5][1] == 13.5


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
    assert unit.skus[0].group_price == "13"
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

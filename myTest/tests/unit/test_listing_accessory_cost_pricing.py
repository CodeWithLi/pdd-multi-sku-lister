"""配件成本定价模式单元测试。"""

from __future__ import annotations

import pytest

from pdd_agent.skills.listing.listing_accessory_cost_pricing import (
    activate_accessory_cost_pricing,
    deactivate_accessory_cost_pricing,
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


def test_resolve_accessory_cost_pricing_bundle_sums_accessory_costs_only_once():
    catalog = {
        "BD032D": PddProductEntry("BD032D", "棕色笔袋", "笔袋", 100, 14.0),
        "YKL020A": PddProductEntry("YKL020A", "磁吸夹", "亚克力", 80, 4.0),
        "YKL004L": PddProductEntry("YKL004L", "套尺", "亚克力", 60, 5.0),
    }
    activate_accessory_cost_pricing(
        cost_map={"YKL020A": 4.09, "YKL004L": 5.09},
        float_min=1.0,
        float_max=1.0,
    )
    _, gp, _ = resolve_accessory_cost_pricing(
        "BD032D",
        BUNDLE_MODEL_CODE,
        catalog,
        {},
        bundle_components=["BD032D", "YKL020A", "YKL004L"],
        listing_scope="BD032/第一套图",
    )
    assert gp == "24.18"


def test_resolve_accessory_cost_pricing_single_adds_one_float():
    catalog = {"BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 10.0)}
    activate_accessory_cost_pricing(cost_map={}, float_min=3.0, float_max=3.0)
    _, gp, _ = resolve_accessory_cost_pricing("BD716A", "BD716A", catalog, {}, listing_scope="scope")
    assert gp == "13"


def test_resolve_accessory_cost_pricing_missing_cost_raises():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 20.0),
        "YKL001N": PddProductEntry("YKL001N", "挂架", "亚克力", 50, 5.0),
    }
    activate_accessory_cost_pricing(cost_map={}, float_min=0.0, float_max=0.0)
    with pytest.raises(ComboPricingError) as exc:
        resolve_accessory_cost_pricing("BD716A", "YKL001N", catalog, {})
    assert exc.value.reason == "jushuitan_cost_missing"


def test_resolve_sku_pricing_with_accessory_cost_if_enabled_returns_none_when_inactive():
    catalog = {"BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 10.0)}
    assert (
        resolve_sku_pricing_with_accessory_cost_if_enabled(
            style_code="BD716A",
            model_code="BD716A",
            catalog=catalog,
            defaults={},
        )
        is None
    )

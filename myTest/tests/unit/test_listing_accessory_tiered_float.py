"""子商品档位浮动规则单元测试。"""

from __future__ import annotations

import random

import pytest

from pdd_agent.skills.listing.listing_accessory_cost_float_registry import (
    _AccessoryCostPart,
    _SkuPricingRow,
    accessory_float_key,
    reconcile_accessory_cost_floats,
)
from pdd_agent.skills.listing.listing_accessory_cost_pricing import (
    activate_accessory_cost_pricing,
    deactivate_accessory_cost_pricing,
    resolve_accessory_cost_pricing,
)
from pdd_agent.skills.listing.listing_accessory_tiered_float import (
    draw_tiered_accessory_float_delta,
    tiered_float_bounds_for_cost,
)
from pdd_agent.skills.listing.listing_price_float import reset_listing_price_float_registry
from pdd_agent.skills.listing.pdd_product_catalog import BUNDLE_MODEL_CODE, PddProductEntry


@pytest.fixture(autouse=True)
def _reset_context():
    deactivate_accessory_cost_pricing()
    reset_listing_price_float_registry(enabled=False, single_float_min=0.0, single_float_max=0.0)
    yield
    deactivate_accessory_cost_pricing()


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        (0.0, (1.0, 1.5)),
        (0.5, (1.0, 1.5)),
        (0.51, (1.5, 2.5)),
        (1.0, (1.5, 2.5)),
        (1.01, (3.0, 4.0)),
        (2.0, (3.0, 4.0)),
        (2.01, (5.0, 7.0)),
        (5.0, (5.0, 7.0)),
    ],
)
def test_tiered_float_bounds_for_cost(cost: float, expected: tuple[float, float]):
    assert tiered_float_bounds_for_cost(cost) == expected


def test_draw_tiered_accessory_float_delta_respects_bounds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(random, "uniform", lambda lo, hi: lo)
    assert draw_tiered_accessory_float_delta(1.0) == 1.5
    monkeypatch.setattr(random, "uniform", lambda lo, hi: hi)
    assert draw_tiered_accessory_float_delta(1.0) == 2.5


def test_reconcile_uses_tiered_accessory_float_per_cost():
    rows = [
        _SkuPricingRow(
            0,
            "BD071@10.00",
            10.0,
            (
                _AccessoryCostPart(accessory_float_key("YKL001A", 1.0), 1.0),
                _AccessoryCostPart(accessory_float_key("YKL010B", 0.4), 0.4),
            ),
            True,
        ),
    ]
    result = reconcile_accessory_cost_floats(
        rows,
        listing_scope="BD071/套1",
        float_min=3.0,
        float_max=3.0,
        accessory_float_for_cost=lambda cost: {
            1.0: 2.0,
            0.4: 1.2,
        }.get(round(cost, 2), 0.0),
    )
    # 主商品浮动 3 + 成本 1.0+0.4 + 配件浮动 2.0+1.2
    assert result[0][2] == 17.6


def test_resolve_accessory_cost_pricing_with_tiered_float():
    catalog = {
        "BD071A": PddProductEntry("BD071A", "笔袋", "笔袋", 100, 10.0),
        "YKL001A": PddProductEntry("YKL001A", "挂件", "挂件", 50, 5.0),
    }
    activate_accessory_cost_pricing(
        cost_map={"YKL001A": 1.0},
        float_min=2.0,
        float_max=2.0,
        tiered_float_enabled=True,
    )
    # 固定主浮动与档位浮动上界，便于断言
    from pdd_agent.skills.listing import listing_accessory_cost_pricing as mod

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod.random, "uniform", lambda lo, hi: hi)
    try:
        inv, gp, sp = resolve_accessory_cost_pricing(
            "BD071A",
            "YKL001A",
            catalog,
            {},
            listing_scope="BD071/第一套图",
        )
    finally:
        monkeypatch.undo()

    # 10 + 2(主浮动) + 1(成本) + 2.5(1元档位浮动上界)
    assert inv == "50"
    assert gp == "15.5"
    assert sp == "15.5"


def test_bundle_each_accessory_gets_own_tiered_float():
    catalog = {
        "BD071A": PddProductEntry("BD071A", "笔袋", "笔袋", 100, 10.0),
        "YKL001A": PddProductEntry("YKL001A", "挂件", "挂件", 50, 5.0),
        "YKL010B": PddProductEntry("YKL010B", "配件", "配件", 50, 5.0),
    }
    activate_accessory_cost_pricing(
        cost_map={"YKL001A": 1.0, "YKL010B": 0.4},
        float_min=0.0,
        float_max=0.0,
        tiered_float_enabled=True,
    )
    from pdd_agent.skills.listing import listing_accessory_cost_pricing as mod

    calls: list[float] = []

    def _fake_draw(cost: float) -> float:
        calls.append(round(cost, 2))
        return {1.0: 2.0, 0.4: 1.2}.get(round(cost, 2), 0.0)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "_accessory_float_drawer", lambda: _fake_draw)
    try:
        inv, gp, _ = resolve_accessory_cost_pricing(
            "BD071A",
            BUNDLE_MODEL_CODE,
            catalog,
            {},
            listing_scope="BD071/第一套图",
            bundle_components=["BD071A", "YKL001A", "YKL010B"],
        )
    finally:
        monkeypatch.undo()

    assert sorted(calls) == [0.4, 1.0]
    # 10 + 0(主浮动) + 1.0+0.4 + 2.0+1.2
    assert inv == "50"
    assert gp == "14.6"

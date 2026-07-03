"""主款款式优先排序。"""

from __future__ import annotations

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.listing_primary_style_first import (
    PrimaryStyleFirstResult,
    reorder_unit_primary_style_first,
)


def _sku(style_code: str, style_name: str, combo: str) -> SkuCombo:
    from pathlib import Path

    return SkuCombo(
        style_code=style_code,
        style_name=style_name,
        model_code=combo,
        model_name="笔袋",
        combo_folder=combo,
        preview_image=Path(f"{combo}.jpg"),
        inventory="1",
        group_price="1",
        single_price="1",
    )


def test_reorder_puts_product_code_style_first():
    unit = ListingUnit(product_code="BD068Q", image_set="第一套图", root=__import__("pathlib").Path("."))
    unit.style_codes = ["BD068A", "BD068C", "BD068Q"]
    unit.skus = [
        _sku("BD068A", "黄色", "BD068A"),
        _sku("BD068C", "绿色", "BD068C"),
        _sku("BD068Q", "蓝色", "BD068Q"),
    ]
    result = reorder_unit_primary_style_first(unit)
    assert result.applied is True
    assert unit.style_codes[0] == "BD068Q"
    assert unit.skus[0].style_code == "BD068Q"
    assert [s.style_code for s in unit.skus] == ["BD068Q", "BD068A", "BD068C"]


def test_noop_when_already_first():
    unit = ListingUnit(product_code="BD068A", image_set="第一套图", root=__import__("pathlib").Path("."))
    unit.style_codes = ["BD068A", "BD068Q"]
    unit.skus = [_sku("BD068A", "黄色", "BD068A"), _sku("BD068Q", "蓝色", "BD068Q")]
    result = reorder_unit_primary_style_first(unit)
    assert result.applied is False
    assert unit.style_codes[0] == "BD068A"

"""规格校验填表（试验）模块单元测试。"""

from __future__ import annotations

from pathlib import Path

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.listing_spec_fill_verified import (
    find_duplicate_spec_pairs,
    find_slot_catalog_mismatches,
    _resolve_config,
)


def _sku(
    style_code: str,
    combo: str,
    model_code: str,
    model_name: str,
) -> SkuCombo:
    return SkuCombo(
        style_code=style_code,
        style_name="蓝色",
        model_code=model_code,
        model_name=model_name,
        combo_folder=combo,
        preview_image=Path(f"{combo}.jpg"),
        inventory="1",
        group_price="1",
        single_price="1",
    )


def test_find_slot_catalog_mismatches_detects_forced_relabel():
    unit = ListingUnit(product_code="BD068Q", image_set="第一套图", root=Path("."))
    unit.skus = [
        _sku("BD068Q", "BD068Q+YKL632A", "YKL632A", "笔袋+套尺"),
    ]
    catalog = {"BD068Q+YKL632A": "笔袋+挂件"}
    mismatches = find_slot_catalog_mismatches(unit, catalog)
    assert len(mismatches) == 1
    assert mismatches[0]["catalog_size"] == "笔袋+挂件"
    assert mismatches[0]["slot_size"] == "笔袋+套尺"


def test_find_slot_catalog_mismatches_ignores_solo():
    unit = ListingUnit(product_code="BD068Q", image_set="第一套图", root=Path("."))
    unit.skus = [_sku("BD068Q", "BD068Q", "BD068Q", "笔袋")]
    catalog = {"BD068Q": "笔袋"}
    assert find_slot_catalog_mismatches(unit, catalog) == []


def test_find_duplicate_spec_pairs():
    skus = [
        _sku("A", "A", "A", "笔袋"),
        _sku("A", "A+X", "X", "笔袋+挂件"),
        _sku("A", "A+Y", "Y", "笔袋+挂件"),
    ]
    dupes = find_duplicate_spec_pairs(skus)
    assert len(dupes) == 1
    assert dupes[0]["reason"] == "duplicate_spec_pair"


def test_resolve_config_scales_for_large_matrix():
    small = _resolve_config(10, 20)
    large = _resolve_config(45, 50)
    assert large.max_retries_per_sku >= small.max_retries_per_sku
    assert large.inter_sku_delay_sec >= small.inter_sku_delay_sec

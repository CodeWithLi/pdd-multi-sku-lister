"""语义槽位对齐单元测试。"""

from __future__ import annotations

from pathlib import Path

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.listing_semantic_slot_alignment import (
    apply_semantic_slot_alignment,
    normalize_semantic_size_label,
    semantic_slot_signature,
)
from pdd_agent.skills.listing.listing_spec_fill_verified import find_slot_catalog_mismatches
from pdd_agent.skills.listing.pdd_product_catalog import BUNDLE_MODEL_CODE
from pdd_agent.skills.listing.slot_alignment import apply_slot_alignment


def _sku(
    style_code: str,
    combo: str,
    model_code: str,
    model_name: str,
    *,
    style_name: str = "白色",
) -> SkuCombo:
    return SkuCombo(
        style_code=style_code,
        style_name=style_name,
        model_code=model_code,
        model_name=model_name,
        combo_folder=combo,
        preview_image=Path(f"{combo}.jpg"),
        inventory="1",
        group_price="1",
        single_price="1",
    )


SLOTS = ["笔袋", "笔袋+挂件", "笔袋+尺子", "笔袋+磁吸夹", "笔袋+套尺"]


def _bd068_style_skus(
    style_code: str,
    accessory_codes: list[str],
    *,
    style_name: str = "白色",
) -> list[SkuCombo]:
    assert len(accessory_codes) == len(SLOTS)
    skus: list[SkuCombo] = []
    for model_code, model_name in zip(accessory_codes, SLOTS):
        combo = style_code if model_code == style_code else f"{style_code}+{model_code}"
        skus.append(
            _sku(style_code, combo, model_code, model_name, style_name=style_name)
        )
    return skus


def _bd068_a_q_unit() -> ListingUnit:
    unit = ListingUnit(product_code="BD068A", image_set="第一套图", root=Path("."))
    a_codes = ["BD068A", "YKL001AC", "YKL008A", "YKL020A", "YKL031D"]
    q_codes = ["BD068Q", "YKL632A", "YKL008A", "YKL020A", "YKL031M"]
    unit.skus = _bd068_style_skus("BD068A", a_codes, style_name="白色") + _bd068_style_skus(
        "BD068Q", q_codes, style_name="白色-Q"
    )
    return unit


def test_normalize_semantic_size_label_strips_disambiguation():
    assert normalize_semantic_size_label("笔袋+挂件(公仔)") == "笔袋+挂件"


def test_semantic_slot_signature_ignores_ykl_code():
    sku = _sku("BD068Q", "BD068Q+YKL632A", "YKL632A", "笔袋+挂件")
    assert semantic_slot_signature(sku) == "size:笔袋+挂件"
    solo = _sku("BD068Q", "BD068Q", "BD068Q", "笔袋")
    assert semantic_slot_signature(solo) == "solo"


def test_semantic_alignment_bd068_q_keeps_catalog_sizes():
    unit = _bd068_a_q_unit()
    catalog_by_combo = {
        str(s.combo_folder): str(s.model_name) for s in unit.skus if s.combo_folder
    }

    result = apply_semantic_slot_alignment(unit)
    assert result.ok
    assert unit.model_codes == SLOTS

    q_skus = [s for s in unit.skus if s.style_code == "BD068Q"]
    assert [s.model_name for s in q_skus] == SLOTS
    assert find_slot_catalog_mismatches(unit, catalog_by_combo) == []


def test_code_alignment_bd068_q_forces_mismatch():
    """旧 YKL 签名会把 Q 款不同编码塞进错误槽位。"""
    unit = _bd068_a_q_unit()
    catalog_by_combo = {
        str(s.combo_folder): str(s.model_name) for s in unit.skus if s.combo_folder
    }

    result = apply_slot_alignment(unit)
    assert result.ok

    mismatches = find_slot_catalog_mismatches(unit, catalog_by_combo)
    assert mismatches
    combo_map = {m["combo_folder"]: m for m in mismatches}
    assert "BD068Q+YKL632A" in combo_map
    assert combo_map["BD068Q+YKL632A"]["catalog_size"] == "笔袋+挂件"
    assert combo_map["BD068Q+YKL632A"]["slot_size"] != "笔袋+挂件"


def test_semantic_alignment_three_slot_pattern():
    """第一套图常见三槽：笔袋、笔袋+挂件、笔袋+套尺。"""
    slots = ["笔袋", "笔袋+挂件", "笔袋+套尺"]
    unit = ListingUnit(product_code="BD100A", image_set="第一套图", root=Path("."))
    unit.skus = [
        _sku("BD100A", "BD100A", "BD100A", "笔袋"),
        _sku("BD100A", "BD100A+YKL001AC", "YKL001AC", "笔袋+挂件"),
        _sku("BD100A", "BD100A+YKL031D", "YKL031D", "笔袋+套尺"),
        _sku("BD100B", "BD100B", "BD100B", "笔袋"),
        _sku("BD100B", "BD100B+YKL632A", "YKL632A", "笔袋+挂件"),
        _sku("BD100B", "BD100B+YKL031M", "YKL031M", "笔袋+套尺"),
    ]
    catalog = {str(s.combo_folder): str(s.model_name) for s in unit.skus}

    result = apply_semantic_slot_alignment(unit)
    assert result.ok
    assert unit.model_codes == slots
    assert find_slot_catalog_mismatches(unit, catalog) == []


def test_semantic_alignment_reports_mismatch_after_forced_relabel():
    unit = ListingUnit(product_code="BD200A", image_set="第一套图", root=Path("."))
    unit.skus = [
        _sku("BD200A", "BD200A", "BD200A", "笔袋"),
        _sku("BD200A", "BD200A+X", "X", "笔袋+挂件"),
        _sku("BD200B", "BD200B", "BD200B", "笔袋"),
        _sku("BD200B", "BD200B+Y", "Y", "笔袋+套装"),
    ]
    catalog = {str(s.combo_folder): str(s.model_name) for s in unit.skus}
    result = apply_semantic_slot_alignment(unit)
    assert result.ok
    mismatches = find_slot_catalog_mismatches(unit, catalog)
    assert len(mismatches) == 1
    assert mismatches[0]["combo_folder"] == "BD200B+Y"
    assert mismatches[0]["catalog_size"] == "笔袋+套装"
    assert mismatches[0]["slot_size"] == "笔袋+挂件"


def test_semantic_bundle_signature():
    unit = ListingUnit(product_code="BD300A", image_set="第一套图", root=Path("."))
    unit.skus = [
        _sku("BD300A", "BD300A", "BD300A", "笔袋"),
        _sku(
            "BD300A",
            "BD300A+A+B",
            BUNDLE_MODEL_CODE,
            "笔袋+套装",
        ),
        _sku("BD300B", "BD300B", "BD300B", "笔袋"),
        _sku(
            "BD300B",
            "BD300B+X+Y",
            BUNDLE_MODEL_CODE,
            "笔袋+套装",
        ),
    ]
    catalog = {str(s.combo_folder): str(s.model_name) for s in unit.skus}
    result = apply_semantic_slot_alignment(unit)
    assert result.ok
    assert find_slot_catalog_mismatches(unit, catalog) == []

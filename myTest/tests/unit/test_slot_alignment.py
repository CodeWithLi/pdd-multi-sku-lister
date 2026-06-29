"""槽位对齐试验模块测试。"""

from pathlib import Path

from pdd_agent.core.config import load_yaml_settings
from pdd_agent.skills.listing.catalog import parse_listing_target
from pdd_agent.skills.listing.listing_spec_pipeline import apply_unit_listing_specs
from pdd_agent.skills.listing.pdd_product_catalog import BUNDLE_MODEL_CODE


def test_slot_alignment_bd720_five_sizes_not_six():
    settings = load_yaml_settings()
    units = parse_listing_target("BD720/第一套图/BD720A", settings, slot_alignment_test=False)
    unit = next(u for u in units if u.product_code == "BD720A")

    apply_unit_listing_specs(unit, allow_ai=False, slot_alignment_test=True)
    assert len(unit.model_codes) == 5
    assert "笔袋+挂件(公仔)" not in unit.model_codes
    assert len(unit.skus) == 10

    b_combo = next(s for s in unit.skus if s.combo_folder == "BD720B+GJ318B")
    a_gj = next(s for s in unit.skus if s.combo_folder == "BD720A+GJ82A")
    assert b_combo.model_name == a_gj.model_name == "笔袋+公仔"


def test_slot_alignment_disabled_keeps_legacy_union():
    settings = load_yaml_settings()
    units = parse_listing_target("BD720/第一套图/BD720A", settings, slot_alignment_test=False)
    unit = next(u for u in units if u.product_code == "BD720A")

    apply_unit_listing_specs(unit, allow_ai=False, slot_alignment_test=False)
    assert len(unit.model_codes) == 6
    assert "笔袋+挂件(公仔)" in unit.model_codes


def test_slot_alignment_pipeline_noop_when_flag_off():
    settings = load_yaml_settings()
    units = parse_listing_target("BD720/第一套图/BD720A", settings)
    unit = next(u for u in units if u.product_code == "BD720A")
    before = list(unit.model_codes)

    errors = apply_unit_listing_specs(unit, allow_ai=False, slot_alignment_test=False)
    assert errors == []
    assert unit.model_codes == before or len(unit.model_codes) == 6


def test_validate_slot_structure_hints_preview_vs_sku(tmp_path, monkeypatch):
    from pdd_agent.skills.listing.slot_alignment import validate_slot_structure
    from pdd_agent.domain.models import ListingUnit, SkuCombo

    set_dir = tmp_path / "BD716" / "第一套图"
    dir_a = set_dir / "BD716A"
    dir_b = set_dir / "BD716B"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)
    for name in [
        "BD716A.png",
        "BD716A+YKL001N.png",
        "BD716A+YKL004.png",
        "BD716A+YKL008E.png",
        "BD716A+YKL020A.png",
    ]:
        (dir_a / name).write_bytes(b"x")
    for name in [
        "BD716B.png",
        "BD716B+YKL001N.png",
        "BD716B+YKL004.png",
        "BD716B+YKL008E.png",
        "BD716B+YKL020A.png",
    ]:
        (dir_b / name).write_bytes(b"x")

    unit = ListingUnit(product_code="BD716A", image_set="第一套图", root=dir_a)
    unit.skus = [
        SkuCombo(
            style_code="BD716A",
            style_name="BD716A",
            model_code="BD716A",
            model_name="BD716A",
            combo_folder="BD716A",
            preview_image=dir_a / "BD716A.png",
            inventory="1",
            group_price="1",
            single_price="1",
        ),
        SkuCombo(
            style_code="BD716A",
            style_name="BD716A",
            model_code="YKL001N",
            model_name="YKL001N",
            combo_folder="BD716A+YKL001N",
            preview_image=dir_a / "BD716A+YKL001N.png",
            inventory="1",
            group_price="1",
            single_price="1",
        ),
        SkuCombo(
            style_code="BD716A",
            style_name="BD716A",
            model_code="YKL008E",
            model_name="YKL008E",
            combo_folder="BD716A+YKL008E",
            preview_image=dir_a / "BD716A+YKL008E.png",
            inventory="1",
            group_price="1",
            single_price="1",
        ),
        SkuCombo(
            style_code="BD716A",
            style_name="BD716A",
            model_code="YKL020A",
            model_name="YKL020A",
            combo_folder="BD716A+YKL020A",
            preview_image=dir_a / "BD716A+YKL020A.png",
            inventory="1",
            group_price="1",
            single_price="1",
        ),
    ]
    for idx, model in enumerate(["BD716B", "YKL001N", "YKL004", "YKL008E", "YKL020A"], start=1):
        unit.skus.append(
            SkuCombo(
                style_code="BD716B",
                style_name="BD716B",
                model_code=model,
                model_name=model,
                combo_folder=f"BD716B+{model}" if model != "BD716B" else "BD716B",
                preview_image=dir_b / f"BD716B{'+' + model if model != 'BD716B' else ''}.png",
                inventory="1",
                group_price="1",
                single_price="1",
            )
        )

    errors = validate_slot_structure(unit)
    assert len(errors) == 1
    assert "BD716A缺YKL004" in errors[0]
    assert "BD716B多1个" in errors[0]
    assert "应为5个" in errors[0]


def test_slot_alignment_matches_signature_not_alphabetical_index(tmp_path):
    """中文主商品 + 短编码文件名：按 combo 签名对齐，避免套餐/挂件槽位对调。"""
    from pdd_agent.domain.models import ListingUnit, SkuCombo
    from pdd_agent.skills.listing.slot_alignment import apply_slot_alignment

    folder_a = "BD037A奶油泡芙笔袋"
    folder_b = "BD037B奶油色长条笔袋"
    set_dir = tmp_path / "BD037" / "第一套"
    dir_a = set_dir / folder_a
    dir_b = set_dir / folder_b
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    for name in [
        f"{folder_a}.png",
        f"{folder_a}+YKL001N.png",
        f"{folder_a}+YKL020A+YKL001N+YKL004L.png",
    ]:
        (dir_a / name).write_bytes(b"x")
    for name in [
        f"{folder_b}.png",
        "BD037B+YKL001N.png",
        "BD037B+YKL001N+YKL020D+YKU007P.png",
    ]:
        (dir_b / name).write_bytes(b"x")

    def _sku(style, combo_folder, model_code, model_name, preview_name):
        preview = (dir_a if style == folder_a else dir_b) / preview_name
        return SkuCombo(
            style_code=style,
            style_name=style,
            model_code=model_code,
            model_name=model_name,
            combo_folder=combo_folder,
            preview_image=preview,
            inventory="1",
            group_price="1",
            single_price="1",
        )

    unit = ListingUnit(product_code=folder_a, image_set="第一套", root=dir_a)
    unit.skus = [
        _sku(folder_a, folder_a, folder_a, "笔袋", f"{folder_a}.png"),
        _sku(folder_a, f"{folder_a}+YKL001N", "YKL001N", "笔袋+挂件", f"{folder_a}+YKL001N.png"),
        _sku(
            folder_a,
            f"{folder_a}+YKL020A+YKL001N+YKL004L",
            BUNDLE_MODEL_CODE,
            "笔袋+套装",
            f"{folder_a}+YKL020A+YKL001N+YKL004L.png",
        ),
        _sku(folder_b, folder_b, folder_b, "笔袋", f"{folder_b}.png"),
        _sku(folder_b, "BD037B+YKL001N", "YKL001N", "笔袋+套装", "BD037B+YKL001N.png"),
        _sku(
            folder_b,
            "BD037B+YKL001N+YKL020D+YKU007P",
            BUNDLE_MODEL_CODE,
            "笔袋+挂件",
            "BD037B+YKL001N+YKL020D+YKU007P.png",
        ),
    ]

    result = apply_slot_alignment(unit)
    assert result.ok

    b_combo = next(s for s in unit.skus if s.combo_folder == "BD037B+YKL001N")
    b_bundle = next(s for s in unit.skus if s.combo_folder == "BD037B+YKL001N+YKL020D+YKU007P")
    assert b_combo.model_name == "笔袋+挂件"
    assert b_bundle.model_name == "笔袋+套装"

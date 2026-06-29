"""槽位对齐：签名冲突时不应重复占用同一尺寸名。"""

from __future__ import annotations

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.catalog import BUNDLE_MODEL_CODE
from pdd_agent.skills.listing.slot_alignment import apply_slot_alignment


def test_slot_alignment_avoids_duplicate_size_when_signature_collides(tmp_path):
    set_dir = tmp_path / "BD339" / "第一套图"
    dir_a = set_dir / "BD339A"
    dir_e = set_dir / "BD339E"
    dir_a.mkdir(parents=True)
    dir_e.mkdir(parents=True)

    def _sku(style, combo, model, name, preview):
        root = dir_a if style == "BD339A" else dir_e
        return SkuCombo(
            style_code=style,
            style_name=style,
            model_code=model,
            model_name=name,
            combo_folder=combo,
            preview_image=root / preview,
            inventory="1",
            group_price="1",
            single_price="1",
        )

    for p in [
        "BD339A.png",
        "BD339A+YKL001A.png",
        "BD339A+YKL004L.png",
        "BD339A+YKL020A.png",
        "BD339A+YKL020A+YKL001A+YKL004L.png",
        "BD339E.png",
        "BD339E+YKL004L.png",
        "BD339E+YKL020A.png",
        "BD339E+YKL632A.png",
        "BD339E+YKL020A+YKL632A+YKL004L.png",
    ]:
        (dir_a if "BD339A" in p else dir_e).joinpath(p).write_bytes(b"x")

    unit = ListingUnit(product_code="BD339A", image_set="第一套图", root=dir_a)
    unit.skus = [
        _sku("BD339A", "BD339A", "BD339A", "笔袋", "BD339A.png"),
        _sku("BD339A", "BD339A+YKL001A", "YKL001A", "笔袋+挂件", "BD339A+YKL001A.png"),
        _sku("BD339A", "BD339A+YKL004L", "YKL004L", "笔袋+套尺", "BD339A+YKL004L.png"),
        _sku("BD339A", "BD339A+YKL020A", "YKL020A", "笔袋+磁吸夹", "BD339A+YKL020A.png"),
        _sku(
            "BD339A",
            "BD339A+YKL020A+YKL001A+YKL004L",
            BUNDLE_MODEL_CODE,
            "笔袋+套装",
            "BD339A+YKL020A+YKL001A+YKL004L.png",
        ),
        _sku("BD339E", "BD339E", "BD339E", "笔袋", "BD339E.png"),
        _sku("BD339E", "BD339E+YKL004L", "YKL004L", "笔袋+套尺", "BD339E+YKL004L.png"),
        _sku("BD339E", "BD339E+YKL020A", "YKL020A", "笔袋+磁吸夹", "BD339E+YKL020A.png"),
        _sku("BD339E", "BD339E+YKL632A", "YKL632A", "笔袋+挂件", "BD339E+YKL632A.png"),
        _sku(
            "BD339E",
            "BD339E+YKL020A+YKL632A+YKL004L",
            BUNDLE_MODEL_CODE,
            "笔袋+套装",
            "BD339E+YKL020A+YKL632A+YKL004L.png",
        ),
    ]

    result = apply_slot_alignment(unit)
    assert result.ok

    e_labels = [s.model_name for s in unit.skus if s.style_code == "BD339E"]
    assert e_labels.count("笔袋+磁吸夹") == 1
    assert "笔袋+挂件" in e_labels
    assert len(set(e_labels)) == 5

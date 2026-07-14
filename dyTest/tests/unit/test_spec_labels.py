"""规格名解析与 Step4 填表辅助测试。"""

from pathlib import Path

from dy_agent.domain.models import ListingUnit, SkuCombo
from dy_agent.skills.listing.spec_labels import ordered_style_names


def _make_unit() -> ListingUnit:
    return ListingUnit(
        product_code="BD716A",
        family_code="BD716",
        image_set="第一套",
        root=Path("."),
        style_codes=["BD716A", "BD716B"],
        model_codes=["笔袋+挂件", "笔袋+套尺"],
        skus=[
            SkuCombo(
                style_code="BD716A",
                style_name="灰色",
                model_code="YKL004L",
                model_name="笔袋+挂件",
                combo_folder="BD716A+YKL004L",
                preview_image=Path("a.png"),
            ),
            SkuCombo(
                style_code="BD716B",
                style_name="米白色",
                model_code="YKL004M",
                model_name="笔袋+套尺",
                combo_folder="BD716B+YKL004M",
                preview_image=Path("b.png"),
            ),
        ],
    )


def test_ordered_style_names_follows_style_codes():
    unit = _make_unit()
    names = ordered_style_names(unit)
    assert names == ["灰色", "米白色"]

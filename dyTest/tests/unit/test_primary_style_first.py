"""主款优先单元测试。"""

from dy_agent.domain.models import ListingUnit, SkuCombo
from dy_agent.skills.listing.listing_primary_style_first import apply_primary_style_first_to_unit
from pathlib import Path


def _sku(style: str, model: str) -> SkuCombo:
    return SkuCombo(
        style_code=style,
        style_name=style,
        model_code=model,
        model_name=model,
        combo_folder=f"{style}+{model}",
        preview_image=Path("x.png"),
    )


def test_primary_style_first_reorders_styles():
    unit = ListingUnit(
        product_code="BD046B",
        family_code="BD046",
        image_set="第一套",
        root=Path("."),
        style_codes=["BD046A", "BD046B"],
        skus=[_sku("BD046A", "M1"), _sku("BD046B", "M1")],
    )
    result = apply_primary_style_first_to_unit(unit, enabled=True)
    assert result is not None
    assert result.applied is True
    assert unit.style_codes[0] == "BD046B"
    assert unit.skus[0].style_code == "BD046B"

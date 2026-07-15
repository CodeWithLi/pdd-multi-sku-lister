"""尺寸简写：笔袋+挂件(公仔) → 笔袋+公仔。"""

from pathlib import Path

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.listing_size_label_paren_rewrite import (
    apply_paren_size_as_product_type,
    apply_paren_size_as_product_type_to_unit,
    rewrite_paren_disambiguation_label,
)


def _sku(style: str, model_code: str, model_name: str, combo: str = "") -> SkuCombo:
    return SkuCombo(
        style_code=style,
        style_name=style,
        model_code=model_code,
        model_name=model_name,
        combo_folder=combo or f"{style}+{model_code}",
        preview_image=Path("."),
    )


def test_rewrite_requires_sibling_base():
    assert (
        rewrite_paren_disambiguation_label(
            "笔袋+挂件(公仔)",
            sibling_bases={"笔袋+挂件"},
        )
        == "笔袋+公仔"
    )
    assert (
        rewrite_paren_disambiguation_label(
            "笔袋+挂件(公仔)",
            sibling_bases={"笔袋+磁吸夹"},
        )
        is None
    )


def test_rewrite_skips_ai_hyphen_labels():
    assert (
        rewrite_paren_disambiguation_label(
            "笔袋+挂件(公仔-鲨鱼)",
            sibling_bases={"笔袋+挂件"},
        )
        is None
    )


def test_apply_bd080_like_collision():
    unit = ListingUnit(
        product_code="BD080A",
        image_set="第一套图",
        listing_label="BD080A/第一套图",
        root=Path("."),
        style_codes=["BD080A"],
        model_codes=["笔袋", "笔袋+挂件", "笔袋+挂件(公仔)", "笔袋+磁吸夹", "笔袋+套装"],
        skus=[
            _sku("BD080A", "BD080A", "笔袋", "BD080A"),
            _sku("BD080A", "YKL001A", "笔袋+挂件", "BD080A+YKL001A"),
            _sku("BD080A", "GJ361A", "笔袋+挂件(公仔)", "BD080A+GJ361A"),
            _sku("BD080A", "YKL020A", "笔袋+磁吸夹", "BD080A+YKL020A"),
            _sku("BD080A", "套装", "笔袋+套装", "BD080A+套装"),
        ],
    )
    result = apply_paren_size_as_product_type(unit)
    assert result.applied
    assert len(result.changes) == 1
    assert result.changes[0].before == "笔袋+挂件(公仔)"
    assert result.changes[0].after == "笔袋+公仔"
    by_code = {s.model_code: s.model_name for s in unit.skus}
    assert by_code["YKL001A"] == "笔袋+挂件"
    assert by_code["GJ361A"] == "笔袋+公仔"
    assert "笔袋+公仔" in unit.model_codes
    assert "笔袋+挂件(公仔)" not in unit.model_codes


def test_disabled_flag_noop():
    unit = ListingUnit(
        product_code="BD080A",
        listing_label="x",
        root=Path("."),
        style_codes=["BD080A"],
        skus=[
            _sku("BD080A", "YKL001A", "笔袋+挂件"),
            _sku("BD080A", "GJ361A", "笔袋+挂件(公仔)"),
        ],
    )
    assert apply_paren_size_as_product_type_to_unit(unit, enabled=False) is None
    assert unit.skus[1].model_name == "笔袋+挂件(公仔)"


def test_skip_when_target_already_exists():
    unit = ListingUnit(
        product_code="BD080A",
        listing_label="x",
        root=Path("."),
        style_codes=["BD080A"],
        skus=[
            _sku("BD080A", "YKL001A", "笔袋+挂件"),
            _sku("BD080A", "GJ361A", "笔袋+挂件(公仔)"),
            _sku("BD080A", "GJ999A", "笔袋+公仔"),
        ],
    )
    result = apply_paren_size_as_product_type(unit)
    assert not result.applied
    assert unit.skus[1].model_name == "笔袋+挂件(公仔)"

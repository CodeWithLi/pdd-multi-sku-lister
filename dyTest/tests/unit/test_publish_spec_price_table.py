"""publish_spec_price_table 单元测试。"""

from __future__ import annotations

from pathlib import Path

from dy_agent.domain.models import SkuCombo
from dy_agent.skills.listing.listing_spec_fill_failure_detail import format_spec_fill_verify_reason
from dy_agent.skills.listing.publish_spec_price_table import (
    _find_duplicate_spec_pairs,
    _row_data_from_sku,
)


def _sku(
    style: str,
    model: str,
    *,
    combo: str = "",
    price: str = "199.9",
    inventory: str = "10",
) -> SkuCombo:
    return SkuCombo(
        style_code=style,
        style_name=style,
        model_code=model,
        model_name=model,
        combo_folder=combo or f"{style}+{model}",
        preview_image=Path("x.png"),
        price=price,
        inventory=inventory,
    )


def test_row_data_from_sku_uses_pricing_and_combo_folder():
    sku = _sku("线条小狗-米色", "笔袋", combo="BD051E", price="12.32", inventory="5366")
    row = _row_data_from_sku(sku, defaults={"price": "99", "inventory": "1"})
    assert row["price"] == "12.32"
    assert row["inventory"] == "5366"
    assert row["merchant_code"] == "BD051E"


def test_row_data_from_sku_falls_back_to_defaults():
    sku = _sku("A", "B", combo="BD001", price="", inventory="")
    row = _row_data_from_sku(sku, defaults={"group_price": "19.9", "inventory": "20"})
    assert row["price"] == "19.9"
    assert row["inventory"] == "20"
    assert row["merchant_code"] == "BD001"


def test_find_duplicate_spec_pairs():
    skus = [
        _sku("A", "S1", combo="C1"),
        _sku("A", "S1", combo="C2"),
    ]
    dupes = _find_duplicate_spec_pairs(skus)
    assert len(dupes) == 1
    assert dupes[0]["reason"] == "duplicate_spec_pair"


def test_format_spec_fill_verify_reason_numbered():
    text = format_spec_fill_verify_reason(
        {
            "failed_items": [
                {
                    "combo_folder": "BD051E",
                    "style": "线条小狗-米色",
                    "size": "笔袋",
                    "reason": "forward_verify_failed",
                    "detail": "price",
                }
            ]
        }
    )
    assert "1." in text
    assert "BD051E" in text
    assert "forward_verify_failed" in text
    assert "price" in text


def test_matrix_row_index():
    from dy_agent.skills.listing.publish_spec_price_table import _matrix_row_index

    assert _matrix_row_index("米色", "笔袋+挂件", ["米色"], ["笔袋+挂件", "笔袋+套尺"]) == 0
    assert _matrix_row_index("米色", "笔袋+套尺", ["米色"], ["笔袋+挂件", "笔袋+套尺"]) == 1
    assert _matrix_row_index("x", "y", ["米色"], ["笔袋+挂件"]) == -1

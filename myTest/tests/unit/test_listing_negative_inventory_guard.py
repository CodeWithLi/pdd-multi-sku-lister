"""负库存上架拦截单元测试。"""

from __future__ import annotations

from pathlib import Path

from pdd_agent.domain.listing_errors import ListingErrorCode
from pdd_agent.domain.models import ListingUnit, PreflightReport, SkuCombo
from pdd_agent.skills.listing.listing_negative_inventory_guard import (
    append_negative_inventory_preflight_issues,
    evaluate_negative_inventory_guard,
    format_negative_inventory_skip_message,
    find_negative_inventory_issues,
)
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry


def _unit(*skus: SkuCombo) -> ListingUnit:
    return ListingUnit(
        product_code="BD351A",
        image_set="第一套图",
        root=Path("BD351A"),
        style_codes=[sku.style_code for sku in skus],
        skus=list(skus),
    )


def _catalog(**entries: tuple[int, float]) -> dict[str, PddProductEntry]:
    return {
        code: PddProductEntry(code, "笔袋", "笔袋", inventory=inv, price=price)
        for code, (inv, price) in entries.items()
    }


def test_format_negative_inventory_skip_message():
    assert format_negative_inventory_skip_message("BD351E") == (
        "BD351E可用库存小于0，跳过该商品上架"
    )


def test_find_negative_inventory_issues_detects_style_code():
    unit = _unit(
        SkuCombo(
            style_code="BD351E",
            style_name="黑色",
            model_code="BD351E",
            model_name="笔袋",
            combo_folder="BD351E",
            preview_image=Path("BD351E.png"),
            inventory="-1574",
        )
    )
    catalog = _catalog(BD351E=(-1574, 9.0), YKL001A=(100, 2.0))
    issues = find_negative_inventory_issues(unit, catalog=catalog)
    assert len(issues) == 1
    assert issues[0].code == "BD351E"
    assert issues[0].available_qty == -1574


def test_find_negative_inventory_issues_ignores_non_negative():
    unit = _unit(
        SkuCombo(
            style_code="BD351A",
            style_name="青苹果",
            model_code="BD351A",
            model_name="笔袋",
            combo_folder="BD351A",
            preview_image=Path("BD351A.png"),
        )
    )
    catalog = _catalog(BD351A=(2080, 9.0))
    assert find_negative_inventory_issues(unit, catalog=catalog) == []


def test_evaluate_negative_inventory_guard_blocks_combo_when_accessory_negative():
    unit = _unit(
        SkuCombo(
            style_code="BD351E",
            style_name="黑色",
            model_code="YKL001A",
            model_name="笔袋+挂件",
            combo_folder="BD351E+YKL001A",
            preview_image=Path("BD351E+YKL001A.png"),
        )
    )
    catalog = _catalog(BD351E=(100, 9.0), YKL001A=(-3, 2.0))
    guard = evaluate_negative_inventory_guard(unit, catalog=catalog)
    assert guard.blocked is True
    assert guard.codes == ["YKL001A"]
    assert "YKL001A可用库存小于0" in guard.failure_message


def test_append_negative_inventory_preflight_issues_excludes_from_valid_units():
    unit = _unit(
        SkuCombo(
            style_code="BD351E",
            style_name="黑色",
            model_code="BD351E",
            model_name="笔袋",
            combo_folder="BD351E",
            preview_image=Path("BD351E.png"),
        )
    )
    report = PreflightReport(units=[unit])
    catalog = _catalog(BD351E=(-1574, 9.0))
    blocked = append_negative_inventory_preflight_issues(report, catalog=catalog)
    assert len(blocked) == 1
    assert report.valid_units == []
    assert report.issues[0].reason_code == ListingErrorCode.NEGATIVE_INVENTORY_SKIP
    assert "BD351E可用库存小于0" in report.issues[0].message

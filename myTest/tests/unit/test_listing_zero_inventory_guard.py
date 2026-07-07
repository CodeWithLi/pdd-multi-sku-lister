"""零库存预检守卫。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.domain.listing_errors import ListingErrorCode
from pdd_agent.domain.models import ListingUnit, PreflightIssue, PreflightReport, SkuCombo
from pdd_agent.skills.listing.listing_zero_inventory_guard import (
    append_zero_inventory_preflight_issues,
    evaluate_zero_inventory_guard,
    find_zero_inventory_issues,
    format_zero_inventory_skip_message,
)
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry


def _catalog(**entries: tuple[int, float]) -> dict[str, PddProductEntry]:
    return {
        code: PddProductEntry(code, "笔袋", "笔袋", inventory=inv, price=price)
        for code, (inv, price) in entries.items()
    }


def _unit(inventory_values: list[int], product_code: str = "BD070A") -> ListingUnit:
    skus = [
        SkuCombo(
            style_code=product_code,
            style_name="测试款式",
            model_code=f"YKL{i:03d}A",
            model_name="测试型号",
            combo_folder=f"{product_code}+YKL{i:03d}A",
            preview_image=Path("D:/tmp/preview.png"),
            inventory=str(value),
        )
        for i, value in enumerate(inventory_values, start=1)
    ]
    return ListingUnit(
        product_code=product_code,
        image_set="第一套图",
        root=Path("D:/tmp"),
        style_codes=[product_code],
        model_codes=[f"YKL{i:03d}A" for i in range(1, len(inventory_values) + 1)],
        skus=skus,
    )


def test_format_zero_inventory_skip_message_includes_code():
    assert format_zero_inventory_skip_message("BD045A") == "BD045A库存为0，跳过该商品上架"


@patch("pdd_agent.skills.listing.listing_zero_inventory_guard._merchant_has_feishu_catalog_row", return_value=True)
def test_evaluate_zero_inventory_guard_blocks_all_zero(_mock_feishu):
    unit = _unit([0, 0])
    catalog = _catalog(BD070A=(0, 9.0), YKL001A=(0, 2.0), YKL002A=(0, 2.0))
    guard = evaluate_zero_inventory_guard(unit, catalog=catalog)
    assert guard.blocked is True
    assert guard.inventories == (0, 0, 0)
    assert "BD070A库存为0" in guard.failure_message
    assert "BD070A聚水潭可用数=0" in guard.system_reason


@patch("pdd_agent.skills.listing.listing_zero_inventory_guard._merchant_has_feishu_catalog_row", return_value=True)
def test_evaluate_zero_inventory_guard_ignores_mixed_positive(_mock_feishu):
    unit = _unit([0, 3])
    catalog = _catalog(BD070A=(0, 9.0), YKL001A=(3, 2.0), YKL002A=(0, 2.0))
    guard = evaluate_zero_inventory_guard(unit, catalog=catalog)
    assert guard.blocked is False


@patch("pdd_agent.skills.listing.listing_zero_inventory_guard._merchant_has_feishu_catalog_row", return_value=True)
def test_find_zero_inventory_issues_ignores_missing_catalog_row(_mock_feishu):
    unit = _unit([0, 0], product_code="BD045A")
    catalog = _catalog(BD045A=(0, 9.0))
    assert find_zero_inventory_issues(unit, catalog=catalog) == []


@patch("pdd_agent.skills.listing.listing_zero_inventory_guard._merchant_has_feishu_catalog_row", return_value=False)
def test_find_zero_inventory_issues_ignores_missing_feishu_merchant_row(_mock_feishu):
    unit = _unit([0, 0], product_code="BD045A")
    catalog = _catalog(BD045A=(0, 9.0), YKL001A=(0, 2.0), YKL002A=(0, 2.0))
    assert find_zero_inventory_issues(unit, catalog=catalog) == []


def test_append_zero_inventory_preflight_issues_skips_existing_errors():
    unit = _unit([0])
    report = PreflightReport(
        units=[unit],
        issues=[
            PreflightIssue(
                level="error",
                listing_label=unit.listing_label,
                reason_code=ListingErrorCode.NEGATIVE_INVENTORY_SKIP,
                message="BD070A可用库存小于0，跳过该商品上架",
            )
        ],
    )

    blocked = append_zero_inventory_preflight_issues(report)

    assert blocked == []
    assert len(report.issues) == 1


@patch("pdd_agent.skills.listing.listing_zero_inventory_guard._merchant_has_feishu_catalog_row", return_value=True)
def test_append_zero_inventory_preflight_issues_adds_error(_mock_feishu):
    unit = _unit([0])
    catalog = _catalog(BD070A=(0, 9.0), YKL001A=(0, 2.0))
    report = PreflightReport(units=[unit], issues=[])

    blocked = append_zero_inventory_preflight_issues(report, catalog=catalog)

    assert len(blocked) == 1
    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue.reason_code == ListingErrorCode.ZERO_INVENTORY_SKIP
    assert issue.listing_label == unit.listing_label
    assert "库存为0" in issue.message


@patch("pdd_agent.skills.listing.listing_zero_inventory_guard._merchant_has_feishu_catalog_row", return_value=False)
def test_append_zero_inventory_skips_when_feishu_merchant_missing(_mock_feishu):
    unit = _unit([0, 0], product_code="BD045A")
    catalog = _catalog(BD045A=(0, 9.0), YKL001A=(0, 2.0), YKL002A=(0, 2.0))
    report = PreflightReport(units=[unit], issues=[])

    blocked = append_zero_inventory_preflight_issues(report, catalog=catalog)

    assert blocked == []
    assert report.issues == []

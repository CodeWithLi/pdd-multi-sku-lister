"""产品状态与可用数上架资格守卫。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdd_agent.domain.listing_errors import ListingErrorCode
from pdd_agent.domain.models import ListingUnit, PreflightReport, SkuCombo
from pdd_agent.skills.listing.listing_product_eligibility_guard import (
    append_product_eligibility_preflight_issues,
    evaluate_product_eligibility_guard,
    is_product_eligible_for_listing,
)
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry


def _unit(product_code: str = "BD070A") -> ListingUnit:
    return ListingUnit(
        product_code=product_code,
        image_set="第一套图",
        root=Path(product_code),
        style_codes=[product_code],
        skus=[
            SkuCombo(
                style_code=product_code,
                style_name="测试款式",
                model_code=product_code,
                model_name="笔袋",
                combo_folder=product_code,
                preview_image=Path(f"{product_code}.png"),
            )
        ],
    )


def _catalog(product_code: str = "BD070A", *, inventory: int = 1) -> dict[str, PddProductEntry]:
    return {
        product_code: PddProductEntry(
            product_code,
            "测试款式",
            "笔袋",
            inventory=inventory,
            price=9.0,
        )
    }


@pytest.mark.parametrize("status", ["现货", "清仓", {"name": "现货"}, {"name": "清仓"}])
def test_is_product_eligible_for_listing_allows_whitelisted_status_with_positive_inventory(status):
    assert is_product_eligible_for_listing(status, 1) is True


@pytest.mark.parametrize(
    ("status", "available_qty"),
    [
        ("下架", 3),
        ("现货", 0),
        ("清仓", -1),
        ("", 3),
        ("现货", None),
    ],
)
def test_is_product_eligible_for_listing_rejects_all_other_conditions(status, available_qty):
    assert is_product_eligible_for_listing(status, available_qty) is False


@pytest.mark.parametrize("status", ["现货", "清仓"])
def test_evaluate_product_eligibility_guard_allows_valid_product(status):
    guard = evaluate_product_eligibility_guard(
        _unit(),
        catalog=_catalog(inventory=5),
        status_by_code={"BD070A": status},
    )

    assert guard.blocked is False
    assert guard.issue is None


def test_evaluate_product_eligibility_guard_blocks_disallowed_status():
    guard = evaluate_product_eligibility_guard(
        _unit(),
        catalog=_catalog(inventory=3),
        status_by_code={"BD070A": "下架"},
    )

    assert guard.blocked is True
    assert guard.issue is not None
    assert guard.issue.product_status == "下架"
    assert guard.issue.available_qty == 3
    assert "现货或清仓且可用数大于0" in guard.failure_message


@pytest.mark.parametrize(
    ("catalog", "status_by_code"),
    [
        ({}, {"BD070A": "现货"}),
        (_catalog(inventory=3), {}),
    ],
)
def test_evaluate_product_eligibility_guard_blocks_missing_data(catalog, status_by_code):
    guard = evaluate_product_eligibility_guard(
        _unit(),
        catalog=catalog,
        status_by_code=status_by_code,
    )

    assert guard.blocked is True


def test_append_product_eligibility_preflight_issues_excludes_invalid_unit():
    unit = _unit()
    report = PreflightReport(units=[unit])

    blocked = append_product_eligibility_preflight_issues(
        report,
        catalog=_catalog(inventory=0),
        status_by_code={"BD070A": "现货"},
    )

    assert len(blocked) == 1
    assert report.valid_units == []
    assert report.issues[0].reason_code == ListingErrorCode.PRODUCT_ELIGIBILITY_SKIP
    assert "可用数为0" in report.issues[0].message

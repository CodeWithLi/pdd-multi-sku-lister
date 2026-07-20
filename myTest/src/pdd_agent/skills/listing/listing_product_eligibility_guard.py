"""上架前产品状态与可用数资格校验。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pdd_agent.domain.listing_errors import ListingErrorCode
from pdd_agent.domain.models import ListingUnit, PreflightIssue, PreflightReport
from pdd_agent.integrations.feishu.field_display import format_single_select
from pdd_agent.integrations.feishu.listing_feishu_product_status_skip import (
    lookup_product_status_by_merchant_codes,
    lookup_product_status_for_merchant_code,
)
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry, _norm_code, find_catalog_entry

ALLOWED_PRODUCT_STATUSES = frozenset({"现货", "清仓"})
PRODUCT_ELIGIBILITY_RULE = "仅产品状态为现货或清仓且可用数大于0时允许上架"


def is_product_eligible_for_listing(product_status: Any, available_qty: int | None) -> bool:
    status = format_single_select(product_status).strip()
    return status in ALLOWED_PRODUCT_STATUSES and available_qty is not None and available_qty > 0


@dataclass(frozen=True)
class ProductEligibilityIssue:
    code: str
    product_status: str
    available_qty: int | None

    @property
    def message(self) -> str:
        status = self.product_status or "未获取到"
        available_qty = "未获取到" if self.available_qty is None else str(self.available_qty)
        return (
            f"{self.code}产品状态为{status}、可用数为{available_qty}，"
            f"不符合上架条件：{PRODUCT_ELIGIBILITY_RULE}"
        )


@dataclass(frozen=True)
class ProductEligibilityGuardResult:
    blocked: bool
    issue: ProductEligibilityIssue | None

    @property
    def failure_message(self) -> str:
        return self.issue.message if self.issue else PRODUCT_ELIGIBILITY_RULE


def evaluate_product_eligibility_guard(
    unit: ListingUnit,
    *,
    catalog: dict[str, PddProductEntry] | None = None,
    status_by_code: dict[str, str] | None = None,
) -> ProductEligibilityGuardResult:
    code = _norm_code(unit.product_code or "")
    if catalog is None:
        from pdd_agent.skills.listing.spec_labels import load_listing_product_catalog

        catalog = load_listing_product_catalog()
    if status_by_code is None:
        status_by_code = lookup_product_status_by_merchant_codes([code] if code else [])

    entry = find_catalog_entry(catalog, code) if code else None
    available_qty = int(entry.inventory) if entry is not None else None
    product_status = lookup_product_status_for_merchant_code(code, status_by_code)
    if is_product_eligible_for_listing(product_status, available_qty):
        return ProductEligibilityGuardResult(blocked=False, issue=None)
    return ProductEligibilityGuardResult(
        blocked=True,
        issue=ProductEligibilityIssue(
            code=code or "未知商品",
            product_status=format_single_select(product_status).strip(),
            available_qty=available_qty,
        ),
    )


def append_product_eligibility_preflight_issues(
    report: PreflightReport,
    *,
    catalog: dict[str, PddProductEntry] | None = None,
    status_by_code: dict[str, str] | None = None,
) -> list[ProductEligibilityGuardResult]:
    if catalog is None:
        from pdd_agent.skills.listing.spec_labels import load_listing_product_catalog

        catalog = load_listing_product_catalog()
    if status_by_code is None:
        codes = [_norm_code(unit.product_code or "") for unit in report.units]
        status_by_code = lookup_product_status_by_merchant_codes([code for code in codes if code])

    existing_error_labels = {
        str(issue.listing_label or "").strip()
        for issue in report.issues or []
        if str(issue.level or "").strip() == "error"
    }
    blocked: list[ProductEligibilityGuardResult] = []
    for unit in report.units:
        if str(unit.listing_label or "").strip() in existing_error_labels:
            continue
        guard = evaluate_product_eligibility_guard(
            unit,
            catalog=catalog,
            status_by_code=status_by_code,
        )
        if not guard.blocked:
            continue
        blocked.append(guard)
        report.issues.append(
            PreflightIssue(
                level="error",
                message=guard.failure_message,
                listing_label=unit.listing_label,
                reason_code=ListingErrorCode.PRODUCT_ELIGIBILITY_SKIP,
            )
        )
    return blocked

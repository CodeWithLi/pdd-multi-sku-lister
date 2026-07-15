"""上架前零库存校验：商品表/聚水潭可用数全部为 0 时跳过套图。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.domain.models import ListingUnit, PreflightIssue, PreflightReport
from pdd_agent.skills.listing.listing_negative_inventory_guard import _collect_unit_product_codes
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry, _norm_code, find_catalog_entry

ZERO_INVENTORY_SKIP_SUFFIX = "库存为0，跳过该商品上架"


@dataclass(frozen=True)
class ZeroInventoryIssue:
    code: str
    available_qty: int


@dataclass(frozen=True)
class ZeroInventoryGuardResult:
    blocked: bool
    issues: tuple[ZeroInventoryIssue, ...]

    @property
    def inventories(self) -> tuple[int, ...]:
        return tuple(item.available_qty for item in self.issues)

    @property
    def failure_message(self) -> str:
        lines = [format_zero_inventory_skip_message(item.code) for item in self.issues]
        if not lines:
            return ZERO_INVENTORY_SKIP_SUFFIX
        if len(lines) == 1:
            return lines[0]
        return ListingErrors.format_numbered(lines)

    @property
    def system_reason(self) -> str:
        parts = [
            f"{item.code}聚水潭可用数={item.available_qty}"
            for item in self.issues
        ]
        return "；".join(parts) if parts else "SKU库存=0"


def format_zero_inventory_skip_message(code: str) -> str:
    normalized = _norm_code(code)
    if not normalized:
        return ZERO_INVENTORY_SKIP_SUFFIX
    return f"{normalized}库存为0，跳过该商品上架"


def _feishu_catalog_preferred() -> bool:
    try:
        from pdd_agent.integrations.feishu.config import load_feishu_config

        cfg = load_feishu_config()
        cat_cfg = cfg.pdd_product_catalog
        price_cfg = cfg.pdd_price_compare
        return bool(
            (cat_cfg.enabled and cat_cfg.prefer_feishu)
            or (price_cfg.enabled and price_cfg.prefer_feishu)
        )
    except Exception:
        return False


def _merchant_has_feishu_catalog_row(merchant_code: str) -> bool:
    """飞书优先时：母商品编码必须能在快照中找到行，否则不算「库存为 0」。"""
    if not _feishu_catalog_preferred():
        return True

    from pdd_agent.integrations.feishu.listing_feishu_catalog import (
        normalize_listing_code,
        snapshot_record_fields,
    )
    from pdd_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot

    code = normalize_listing_code(merchant_code)
    if not code:
        return False

    snapshot = get_listing_feishu_snapshot()
    if snapshot is None:
        return True

    source = str(getattr(snapshot, "source", "") or "").strip()
    if source in {"feishu_query_failed", "feishu_empty", "feishu_table_missing", "feishu_not_configured"}:
        return False

    queried = getattr(snapshot, "queried_codes", None) or set()
    if code not in queried:
        return True

    return snapshot_record_fields(snapshot, code) is not None


def find_zero_inventory_issues(
    unit: ListingUnit,
    *,
    catalog: dict[str, PddProductEntry] | None = None,
) -> list[ZeroInventoryIssue]:
    """从商品表找出可用库存 == 0 的编码；缺行/飞书无母商品数据时不判零库存。"""
    if not unit.skus:
        return []

    merchant = _norm_code(unit.product_code or "")
    if merchant and not _merchant_has_feishu_catalog_row(merchant):
        return []

    if catalog is None:
        from pdd_agent.skills.listing.spec_labels import load_listing_product_catalog

        catalog = load_listing_product_catalog()

    codes = _collect_unit_product_codes(unit)
    if not codes:
        return []

    issues: list[ZeroInventoryIssue] = []
    flagged: set[str] = set()

    for code in codes:
        entry = find_catalog_entry(catalog, code)
        if entry is None:
            return []
        available_qty = int(entry.inventory or 0)
        if available_qty < 0:
            return []
        if available_qty == 0 and code not in flagged:
            flagged.add(code)
            issues.append(ZeroInventoryIssue(code=code, available_qty=0))

    if len(issues) == len(dict.fromkeys(codes)):
        return issues
    return []


def evaluate_zero_inventory_guard(
    unit: ListingUnit,
    *,
    catalog: dict[str, PddProductEntry] | None = None,
) -> ZeroInventoryGuardResult:
    issues = find_zero_inventory_issues(unit, catalog=catalog)
    return ZeroInventoryGuardResult(blocked=bool(issues), issues=tuple(issues))


def _issue_blocks_zero_inventory(issue: Any) -> bool:
    if str(getattr(issue, "level", "") or "").strip() != "error":
        return False
    reason = str(getattr(issue, "reason_code", "") or "").strip()
    if not reason:
        return True
    if reason == ListingErrorCode.ZERO_INVENTORY_SKIP:
        return True
    if reason.startswith("feishu_") or reason.startswith("preflight_"):
        return True
    return reason in {
        ListingErrorCode.NEGATIVE_INVENTORY_SKIP,
        ListingErrorCode.PREFLIGHT_NO_SKUS,
        ListingErrorCode.PREFLIGHT_CATALOG,
        ListingErrorCode.FEISHU_PRODUCT_CATALOG_MISSING,
        ListingErrorCode.FEISHU_PRICING_MISSING,
        ListingErrorCode.FEISHU_CONTROL_MISSING,
        ListingErrorCode.FEISHU_ROW_NOT_FOUND,
        ListingErrorCode.NO_VALID_UNITS,
    }


def append_zero_inventory_preflight_issues(
    report: PreflightReport,
    *,
    catalog: dict[str, PddProductEntry] | None = None,
) -> list[ZeroInventoryGuardResult]:
    blocked: list[ZeroInventoryGuardResult] = []
    existing_error_labels = {
        str(getattr(issue, "listing_label", "") or "").strip()
        for issue in report.issues or []
        if _issue_blocks_zero_inventory(issue)
    }
    for unit in report.units:
        if str(unit.listing_label or "").strip() in existing_error_labels:
            continue
        guard = evaluate_zero_inventory_guard(unit, catalog=catalog)
        if not guard.blocked:
            continue
        blocked.append(guard)
        report.issues.append(
            PreflightIssue(
                level="error",
                message=guard.failure_message,
                listing_label=unit.listing_label,
                reason_code=ListingErrorCode.ZERO_INVENTORY_SKIP,
            )
        )
    return blocked


def schedule_zero_inventory_skip_feishu_log(
    *,
    account_id: str,
    account_name: str,
    unit: ListingUnit,
    guard: ZeroInventoryGuardResult,
    publish_start=None,
    publish_end=None,
    duration_seconds: float | None = None,
    pipeline_id: str = "",
    run_id: str = "",
) -> None:
    from pdd_agent.integrations.feishu.pdd_upload_sync import schedule_pdd_upload_failure_log

    schedule_pdd_upload_failure_log(
        account_id=account_id,
        account_name=account_name,
        listing_label=unit.listing_label,
        merchant_code=unit.merchant_code,
        record_type="跳过",
        reason_code=ListingErrorCode.ZERO_INVENTORY_SKIP,
        failure_reason=guard.failure_message,
        pipeline_id=str(pipeline_id or "").strip(),
        run_id=str(run_id or "").strip(),
        report_platform="拼多多",
        publish_start=publish_start,
        publish_end=publish_end,
        duration_seconds=duration_seconds,
    )

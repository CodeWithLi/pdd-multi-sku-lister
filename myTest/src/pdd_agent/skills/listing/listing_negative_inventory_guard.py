"""上架前负库存校验：聚水潭「可用数」< 0 时跳过套图并写飞书失败日志。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.domain.models import ListingUnit, PreflightIssue, PreflightReport
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry, _norm_code, find_catalog_entry

NEGATIVE_INVENTORY_SKIP_SUFFIX = "可用库存小于0，跳过该商品上架"


@dataclass(frozen=True)
class NegativeInventoryIssue:
    code: str
    available_qty: int


@dataclass(frozen=True)
class NegativeInventoryGuardResult:
    blocked: bool
    issues: tuple[NegativeInventoryIssue, ...]

    @property
    def codes(self) -> list[str]:
        return [item.code for item in self.issues]

    @property
    def failure_message(self) -> str:
        lines = [format_negative_inventory_skip_message(item.code) for item in self.issues]
        if not lines:
            return NEGATIVE_INVENTORY_SKIP_SUFFIX
        if len(lines) == 1:
            return lines[0]
        return ListingErrors.format_numbered(lines)

    @property
    def system_reason(self) -> str:
        parts = [
            f"{item.code}聚水潭可用数={item.available_qty}"
            for item in self.issues
        ]
        return "；".join(parts)


def format_negative_inventory_skip_message(code: str) -> str:
    normalized = _norm_code(code)
    if not normalized:
        return NEGATIVE_INVENTORY_SKIP_SUFFIX
    return f"{normalized}{NEGATIVE_INVENTORY_SKIP_SUFFIX}"


def _collect_unit_product_codes(unit: ListingUnit) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    def add(raw: str) -> None:
        code = _norm_code(raw)
        if not code or code in seen:
            return
        seen.add(code)
        ordered.append(code)

    for sku in unit.skus or []:
        add(sku.style_code)
        add(sku.model_code)
        combo = str(sku.combo_folder or "").strip()
        if combo:
            for part in combo.split("+"):
                add(part)

    return ordered


def find_negative_inventory_issues(
    unit: ListingUnit,
    *,
    catalog: dict[str, PddProductEntry] | None = None,
) -> list[NegativeInventoryIssue]:
    """从商品表（已含聚水潭可用数覆盖）找出可用库存 < 0 的编码。"""
    if not unit.skus:
        return []

    if catalog is None:
        from pdd_agent.skills.listing.spec_labels import load_listing_product_catalog

        catalog = load_listing_product_catalog()

    issues: list[NegativeInventoryIssue] = []
    flagged: set[str] = set()

    for code in _collect_unit_product_codes(unit):
        entry = find_catalog_entry(catalog, code)
        if entry is None:
            continue
        available_qty = int(entry.inventory or 0)
        if available_qty < 0 and code not in flagged:
            flagged.add(code)
            issues.append(NegativeInventoryIssue(code=code, available_qty=available_qty))

    return issues


def evaluate_negative_inventory_guard(
    unit: ListingUnit,
    *,
    catalog: dict[str, PddProductEntry] | None = None,
) -> NegativeInventoryGuardResult:
    issues = find_negative_inventory_issues(unit, catalog=catalog)
    return NegativeInventoryGuardResult(blocked=bool(issues), issues=tuple(issues))


def append_negative_inventory_preflight_issues(
    report: PreflightReport,
    *,
    catalog: dict[str, PddProductEntry] | None = None,
) -> list[NegativeInventoryGuardResult]:
    """把负库存套图写入 preflight error，使其从 valid_units 中排除。"""
    blocked: list[NegativeInventoryGuardResult] = []
    for unit in report.units:
        guard = evaluate_negative_inventory_guard(unit, catalog=catalog)
        if not guard.blocked:
            continue
        blocked.append(guard)
        report.issues.append(
            PreflightIssue(
                level="error",
                message=guard.failure_message,
                listing_label=unit.listing_label,
                reason_code=ListingErrorCode.NEGATIVE_INVENTORY_SKIP,
            )
        )
    return blocked


def build_listing_skip_result(
    run_id: str,
    account_id: str,
    unit: ListingUnit,
    *,
    guard: NegativeInventoryGuardResult,
) -> dict[str, Any]:
    """负库存跳过：返回与 upload_one_listing 一致的结果结构。"""
    from pdd_agent.skills.listing.upload import _finish_listing

    message = guard.failure_message
    return _finish_listing(
        run_id,
        account_id,
        unit,
        status="skipped",
        reason=ListingErrorCode.NEGATIVE_INVENTORY_SKIP,
        error=message,
        legacy_status="skipped",
        phase="preflight",
        step="negative_inventory_guard",
        extra={
            "negative_inventory_codes": guard.codes,
            "system_reason": guard.system_reason,
        },
    )


def schedule_negative_inventory_skip_feishu_log(
    *,
    account_id: str,
    account_name: str,
    unit: ListingUnit,
    guard: NegativeInventoryGuardResult,
    publish_start=None,
    publish_end=None,
    duration_seconds: float | None = None,
    pipeline_id: str = "",
    run_id: str = "",
) -> None:
    """写入飞书 PDD 发布失败/跳过日志。"""
    from pdd_agent.integrations.feishu.pdd_upload_sync import schedule_pdd_upload_failure_log

    schedule_pdd_upload_failure_log(
        account_id=account_id,
        account_name=account_name,
        listing_label=unit.listing_label,
        merchant_code=unit.merchant_code,
        record_type="跳过",
        failure_reason=guard.failure_message,
        pipeline_id=str(pipeline_id or "").strip(),
        run_id=str(run_id or "").strip(),
        report_platform="拼多多",
        publish_start=publish_start,
        publish_end=publish_end,
        duration_seconds=duration_seconds,
    )

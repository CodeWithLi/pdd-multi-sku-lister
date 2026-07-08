"""预检失败到飞书失败表的桥接模块。

目标：把需要对运营可见的 preflight 失败，以独立封装方式补写到飞书失败表。
当前仅处理 negative_inventory_skip，主流程只需薄引用本模块。
"""

from __future__ import annotations

from typing import Iterable

from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.core.logging import get_logger
from pdd_agent.domain.listing_errors import ListingErrorCode
from pdd_agent.domain.models import ListingUnit, PreflightIssue, PreflightReport
from pdd_agent.skills.listing.listing_negative_inventory_guard import (
    NegativeInventoryGuardResult,
    evaluate_negative_inventory_guard,
    schedule_negative_inventory_skip_feishu_log,
)
from pdd_agent.skills.listing.listing_zero_inventory_guard import (
    ZeroInventoryGuardResult,
    evaluate_zero_inventory_guard,
    schedule_zero_inventory_skip_feishu_log,
)

logger = get_logger(__name__)

PREFLIGHT_FEISHU_BRIDGE_REASON_CODES = frozenset(
    {
        ListingErrorCode.NEGATIVE_INVENTORY_SKIP,
        ListingErrorCode.ZERO_INVENTORY_SKIP,
    }
)


def is_preflight_feishu_bridge_reason(reason_code: str) -> bool:
    """预检桥接模块已即时写飞书的 reason_code，结束汇总时不再重复落表。"""
    return str(reason_code or "").strip() in PREFLIGHT_FEISHU_BRIDGE_REASON_CODES


def _iter_issues(report: PreflightReport) -> Iterable[PreflightIssue]:
    for issue in report.issues or []:
        if isinstance(issue, PreflightIssue):
            yield issue


def _unit_by_label(report: PreflightReport, listing_label: str) -> ListingUnit | None:
    target = str(listing_label or "").strip()
    if not target:
        return None
    for unit in report.units or []:
        if str(unit.listing_label or "").strip() == target:
            return unit
    return None


def _resolve_negative_inventory_guard(
    report: PreflightReport,
    issue: PreflightIssue,
) -> tuple[ListingUnit | None, NegativeInventoryGuardResult | None]:
    unit = _unit_by_label(report, issue.listing_label)
    if not unit:
        return None, None
    guard = evaluate_negative_inventory_guard(unit)
    if not guard.blocked:
        return unit, None
    return unit, guard


def _resolve_zero_inventory_guard(
    report: PreflightReport,
    issue: PreflightIssue,
) -> tuple[ListingUnit | None, ZeroInventoryGuardResult | None]:
    unit = _unit_by_label(report, issue.listing_label)
    if not unit:
        return None, None
    guard = evaluate_zero_inventory_guard(unit)
    if not guard.blocked:
        return unit, None
    return unit, guard


def sync_preflight_failures_to_feishu(
    *,
    account_id: str,
    report: PreflightReport,
) -> int:
    """将预检失败同步到飞书失败表。

    返回成功尝试同步的条数；异常仅记录日志，不中断主流程。
    """
    account_id = str(account_id or "").strip()
    if not account_id or report is None:
        return 0

    shop_name = resolve_account_display_name(account_id)

    synced = 0
    for issue in _iter_issues(report):
        if str(issue.level or "").strip() != "error":
            continue
        try:
            unit = None
            guard: NegativeInventoryGuardResult | ZeroInventoryGuardResult | None = None
            reason = str(issue.reason_code or "").strip()
            if reason == ListingErrorCode.NEGATIVE_INVENTORY_SKIP:
                unit, guard = _resolve_negative_inventory_guard(report, issue)
            elif reason == ListingErrorCode.ZERO_INVENTORY_SKIP:
                unit, guard = _resolve_zero_inventory_guard(report, issue)
            else:
                continue
            if unit is None:
                logger.warning(
                    "preflight feishu bridge missing unit account=%s label=%s",
                    account_id,
                    issue.listing_label,
                )
                continue
            if guard is None:
                logger.warning(
                    "preflight feishu bridge guard not blocked account=%s label=%s",
                    account_id,
                    issue.listing_label,
                )
                continue
            if reason == ListingErrorCode.NEGATIVE_INVENTORY_SKIP:
                schedule_negative_inventory_skip_feishu_log(
                    account_id=account_id,
                    account_name=shop_name,
                    unit=unit,
                    guard=guard,
                )
            else:
                schedule_zero_inventory_skip_feishu_log(
                    account_id=account_id,
                    account_name=shop_name,
                    unit=unit,
                    guard=guard,
                )
            synced += 1
        except Exception:
            logger.exception(
                "preflight feishu bridge sync failed account=%s label=%s reason=%s",
                account_id,
                issue.listing_label,
                issue.reason_code,
            )
    return synced

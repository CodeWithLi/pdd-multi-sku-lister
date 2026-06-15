"""
上架规格流水线（薄封装）

常规 enrich + 可选试验性槽位对齐。业务代码只应通过本模块传入 slot_alignment_test。
"""

from __future__ import annotations

from pdd_agent.domain.models import ListingUnit, PreflightIssue
from pdd_agent.skills.listing.spec_labels import enrich_listing_unit_specs


def apply_unit_listing_specs(
    unit: ListingUnit,
    *,
    account_id: str = "",
    allow_ai: bool = True,
    slot_alignment_test: bool = False,
) -> list[str]:
    """
    解析单元规格名。返回 error 级消息列表（空表示通过）。
    slot_alignment_test=False 时与原先 enrich_listing_unit_specs 行为一致。
    """
    enrich_listing_unit_specs(unit, account_id=account_id, allow_ai=allow_ai)
    if not slot_alignment_test:
        return []

    from pdd_agent.skills.listing.slot_alignment import apply_slot_alignment

    result = apply_slot_alignment(unit, account_id=account_id)
    if result.ok:
        return []
    return list(result.errors)


def preflight_issues_from_slot_errors(errors: list[str]) -> list[PreflightIssue]:
    return [PreflightIssue(level="error", message=msg, listing_label=_label_from_msg(msg)) for msg in errors]


def _label_from_msg(message: str) -> str:
    text = message.strip()
    if text.startswith("[") and "]" in text:
        return text[1 : text.index("]")]
    return ""

"""多规格填表流水线（规格校验、主款优先等）— 第一步后接入。"""

from __future__ import annotations

from dy_agent.domain.models import ListingUnit
from dy_agent.skills.listing.listing_options import ListingOptions


def prepare_spec_pipeline_flags(options: ListingOptions) -> dict:
    """
    预留：第二步起根据开关走不同规格填表策略。
    当前 step1 仅记录开关，便于后续接入 slot_alignment / spec_fill_verify / primary_style_first。
    """
    return {
        "slot_alignment_test": options.slot_alignment_test,
        "spec_fill_verify_test": options.spec_fill_verify_test,
        "primary_style_first_test": options.primary_style_first_test,
        "ready": False,
        "note": "step2_pending",
    }


def run_spec_fill_pipeline(
    page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """占位：规格校验填表、主款款式优先等。"""
    raise NotImplementedError(
        f"[{account_id}] [{unit.listing_label}] 规格填表流水线尚未实现（flags={prepare_spec_pipeline_flags(options)}）"
    )

"""LangGraph 各子图共享的状态类型。"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from dy_agent.domain.models import ListingUnit, PlannedTask, PreflightReport


class OrchestratorState(TypedDict, total=False):
    user_message: str
    planned_tasks: list[PlannedTask]
    plan_summary: str
    errors: Annotated[list[str], operator.add]


class ListingState(TypedDict, total=False):
    account_id: str
    product_codes: list[str]
    dry_run: bool
    category_keyword: str
    run_id: str
    assets_root: str
    material_source: str
    # 试验开关（与 settings.listing / 拼多多 pipeline 对齐）
    slot_alignment_test: bool
    spec_fill_verify_test: bool
    primary_style_first_test: bool
    category_next_burst_demo: bool
    accessory_cost_pricing: bool
    accessory_tiered_float: bool
    preflight: PreflightReport
    units: list[ListingUnit]
    results: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    phase: str
    finished: bool

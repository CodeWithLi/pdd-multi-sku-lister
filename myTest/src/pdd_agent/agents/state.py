"""
LangGraph 各子图共享的状态类型。

Annotated[..., operator.add] 表示多节点返回的列表会合并，而非覆盖。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from pdd_agent.domain.models import ListingUnit, PlannedTask, PreflightReport


class OrchestratorState(TypedDict, total=False):
    """总编排图状态：自然语言 → 任务计划列表。"""

    user_message: str
    planned_tasks: list[PlannedTask]
    plan_summary: str
    errors: Annotated[list[str], operator.add]


class ListingState(TypedDict, total=False):
    """上架子图状态：preflight → browser → report。"""

    account_id: str
    product_codes: list[str]
    dry_run: bool  # True 时只做校验，不启动浏览器
    category_keyword: str
    preflight: PreflightReport
    units: list[ListingUnit]
    current_index: int  # 多单元顺序上架时的游标（预留）
    results: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    phase: str
    finished: bool


class DelistState(TypedDict, total=False):
    """下架子图状态。"""

    account_id: str
    dry_run: bool
    skip_browser: bool
    delist_params: dict[str, Any]
    results: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    phase: str
    finished: bool

"""任务相关 HTTP 接口。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pdd_agent.agents.listing import build_listing_graph
from pdd_agent.agents.orchestrator import build_orchestrator_graph
from pdd_agent.core.config import get_account, load_yaml_settings

router = APIRouter(prefix="/tasks", tags=["tasks"])


class PlanRequest(BaseModel):
    message: str


class ListingRequest(BaseModel):
    account_id: str
    product_codes: list[str] = Field(default_factory=list)
    dry_run: bool = False
    category_keyword: str = "玩偶"


@router.post("/plan")
async def plan_tasks(body: PlanRequest):
    """自然语言 → Orchestrator 任务计划。"""
    graph = build_orchestrator_graph()
    result = graph.invoke({"user_message": body.message})
    return {
        "plan_summary": result.get("plan_summary"),
        "planned_tasks": [t.model_dump() for t in result.get("planned_tasks", [])],
    }


@router.post("/listing")
async def run_listing(body: ListingRequest):
    """异步执行 Listing LangGraph 子图。"""
    settings = load_yaml_settings()
    account = get_account(settings, body.account_id)
    if not account:
        return {"error": f"unknown account: {body.account_id}"}

    codes = body.product_codes or account.product_codes
    graph = build_listing_graph()
    result = await graph.ainvoke(
        {
            "account_id": body.account_id,
            "product_codes": codes,
            "dry_run": body.dry_run,
            "category_keyword": body.category_keyword,
        }
    )
    return result

"""任务触发 API。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from dy_agent.agents.listing import build_listing_graph
from dy_agent.agents.orchestrator import build_orchestrator_graph
from dy_agent.api.schemas.tasks import (
    ListingTaskRequest,
    ListingTaskResponse,
    PlanRequest,
    PlanResponse,
)
from dy_agent.api.services.listing_state import listing_flags_from_request
from dy_agent.core.config import get_account, load_yaml_settings
from dy_agent.domain.enums import AgentKind, RunStatus
from dy_agent.storage import TaskRunStore

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _json_safe(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def _summarize_listing_message(result: dict) -> str:
    if result.get("errors"):
        return "; ".join(str(e) for e in result["errors"])
    results = result.get("results") or []
    if not results:
        return "listing finished"
    first = results[0] if isinstance(results[0], dict) else {}
    if first.get("summary"):
        return str(first["summary"])
    if first.get("message"):
        return str(first["message"])
    if first.get("status") == "step1_done":
        return f"{first.get('listing_label', '')} step1 完成"
    return "listing finished"


@router.post("/plan", response_model=PlanResponse)
def plan_tasks(body: PlanRequest):
    graph = build_orchestrator_graph()
    result = graph.invoke({"user_message": body.message})
    tasks = [_json_safe(t) for t in result.get("planned_tasks") or []]
    return PlanResponse(
        plan_summary=result.get("plan_summary") or "",
        planned_tasks=tasks,
    )


async def _execute_listing(run_id: str, body: ListingTaskRequest) -> None:
    settings = load_yaml_settings()
    account = get_account(settings, body.account_id)
    if not account:
        TaskRunStore().finish(run_id, RunStatus.FAILED, f"unknown account: {body.account_id}")
        return

    codes = body.product_codes or account.product_codes
    graph = build_listing_graph()
    result = await graph.ainvoke(
        {
            "account_id": body.account_id,
            "product_codes": codes,
            "dry_run": body.dry_run,
            "category_keyword": body.category_keyword or settings.listing.category_keyword,
            "run_id": run_id,
            **listing_flags_from_request(body, settings.listing),
        }
    )
    result = _json_safe(result)
    status = RunStatus.SUCCESS if not result.get("errors") else RunStatus.FAILED
    labels = [
        str(item.get("listing_label") or "")
        for item in (result.get("results") or [])
        if isinstance(item, dict) and item.get("listing_label")
    ]
    TaskRunStore().finish(
        run_id,
        status,
        _summarize_listing_message(result),
        result=result,
        listing_labels=labels,
    )


@router.post("/listing", response_model=ListingTaskResponse)
async def create_listing_task(body: ListingTaskRequest, background_tasks: BackgroundTasks):
    settings = load_yaml_settings()
    if not get_account(settings, body.account_id):
        raise HTTPException(status_code=400, detail=f"unknown account: {body.account_id}")

    store = TaskRunStore()
    run = store.create_run(AgentKind.LISTING, body.account_id)
    background_tasks.add_task(_execute_listing, run.run_id, body)
    return ListingTaskResponse(run_id=run.run_id, status=RunStatus.RUNNING.value, message="queued")

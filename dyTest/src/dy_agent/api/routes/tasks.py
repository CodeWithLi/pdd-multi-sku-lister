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
from dy_agent.core.config import load_yaml_settings
from dy_agent.db.repositories import get_account_config
from dy_agent.domain.enums import AgentKind, RunStatus
from dy_agent.integrations.feishu.listing_bootstrap import bootstrap_listing_feishu
from dy_agent.integrations.minio.material import prepare_listing_assets
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
    if first.get("status") == "success":
        pid = first.get("dy_product_id") or (first.get("goods_list_capture") or {}).get("dy_product_id")
        return f"{first.get('listing_label', '')} 发布成功 ID={pid or '-'}"
    if first.get("status") == "step5_done":
        return f"{first.get('listing_label', '')} step5 完成（价格/库存/商家编码）"
    if first.get("status") == "step4_done":
        return f"{first.get('listing_label', '')} step4 完成（颜色分类/尺寸大小 创建类型填表）"
    if first.get("status") == "step3_done":
        return f"{first.get('listing_label', '')} step3 完成（价格库存/手动填写）"
    if first.get("status") == "step2_done":
        return f"{first.get('listing_label', '')} step2 完成（白底图/详情图）"
    if first.get("status") in {"step1_done", "step2_done"}:
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
    account = get_account_config(settings, body.account_id)
    if not account:
        TaskRunStore().finish(run_id, RunStatus.FAILED, f"unknown account: {body.account_id}")
        return

    codes = body.product_codes or account.product_codes
    try:
        material_source, assets_root = prepare_listing_assets(
            codes,
            material_source=body.material_source or None,
        )
    except Exception as exc:
        TaskRunStore().finish(run_id, RunStatus.FAILED, str(exc))
        return

    graph = build_listing_graph()
    listing_flags = listing_flags_from_request(body, settings.listing)
    feishu_bootstrap = bootstrap_listing_feishu(
        accessory_cost_pricing=bool(listing_flags.get("accessory_cost_pricing")),
        accessory_tiered_float=bool(listing_flags.get("accessory_tiered_float")),
    )
    invoke_state: dict = {
        "account_id": body.account_id,
        "product_codes": codes,
        "dry_run": body.dry_run,
        "category_keyword": body.category_keyword or settings.listing.category_keyword,
        "run_id": run_id,
        "material_source": material_source,
        "feishu_bootstrap": feishu_bootstrap,
        **listing_flags,
    }
    if assets_root is not None:
        invoke_state["assets_root"] = str(assets_root)

    result = await graph.ainvoke(invoke_state)
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
    if not get_account_config(settings, body.account_id):
        raise HTTPException(status_code=400, detail=f"unknown account: {body.account_id}")

    store = TaskRunStore()
    run = store.create_run(AgentKind.LISTING, body.account_id)
    background_tasks.add_task(_execute_listing, run.run_id, body)
    return ListingTaskResponse(run_id=run.run_id, status=RunStatus.RUNNING.value, message="queued")

"""任务触发接口：规划、上架。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from pdd_agent.api.schemas.tasks import (
    DelistTaskRequest,
    DelistTaskResponse,
    ListingTaskRequest,
    ListingTaskResponse,
    PlanRequest,
    PlanResponse,
)
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.api.services.task_runner import (
    create_delist_run,
    create_listing_run,
    execute_delist,
    execute_listing,
    plan_tasks,
)
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.domain.enums import RunStatus
from pdd_agent.storage import TaskRunStore

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/plan", response_model=PlanResponse)
def tasks_plan(body: PlanRequest):
    """自然语言 → Orchestrator 任务计划。"""
    return plan_tasks(body.message)


@router.post("/listing", response_model=ListingTaskResponse)
async def tasks_listing(body: ListingTaskRequest, background: BackgroundTasks):
    """
    触发 listing 子图。

    - dry_run=True：默认同步返回校验结果（快）
    - dry_run=False 且 background=True：后台跑浏览器，立即返回 run_id
    - background=False：同步等待（可能较慢，易超时）
    """
    settings = load_yaml_settings()
    if not get_account_or_none(body.account_id, settings):
        raise HTTPException(status_code=404, detail=f"unknown account: {body.account_id}")

    run_id = create_listing_run(body.account_id)
    codes = body.product_codes

    async def _job():
        await execute_listing(
            run_id=run_id,
            account_id=body.account_id,
            product_codes=codes,
            dry_run=body.dry_run,
            category_keyword=body.category_keyword,
        )

    # dry_run 通常很快，默认同步返回完整结果
    if body.dry_run or not body.background:
        result = await execute_listing(
            run_id=run_id,
            account_id=body.account_id,
            product_codes=codes,
            dry_run=body.dry_run,
            category_keyword=body.category_keyword,
        )
        record = TaskRunStore().load(run_id)
        status = record.status if record else RunStatus.SUCCESS
        return ListingTaskResponse(run_id=run_id, status=status, result=result)

    background.add_task(_job)
    return ListingTaskResponse(
        run_id=run_id,
        status=RunStatus.RUNNING,
        message="任务已在后台启动，请通过 GET /api/runs/{run_id} 查询进度",
    )


@router.post("/delist", response_model=DelistTaskResponse)
async def tasks_delist(body: DelistTaskRequest, background: BackgroundTasks):
    """触发下架子图（扫描在售商品并按时间门槛下架）。"""
    settings = load_yaml_settings()
    if not get_account_or_none(body.account_id, settings):
        raise HTTPException(status_code=404, detail=f"unknown account: {body.account_id}")

    run_id = create_delist_run(body.account_id)
    params = {
        "min_created_after": body.min_created_after or settings.delist.min_created_after,
        "merchant_code_contains": body.merchant_code_contains or settings.delist.merchant_code_contains,
        "max_delist_per_run": body.max_delist_per_run,
    }
    if body.dry_run is not None:
        params["dry_run"] = body.dry_run

    async def _job():
        await execute_delist(
            run_id=run_id,
            account_id=body.account_id,
            delist_params=params,
        )

    if not body.background:
        result = await execute_delist(
            run_id=run_id,
            account_id=body.account_id,
            delist_params=params,
        )
        record = TaskRunStore().load(run_id)
        status = record.status if record else RunStatus.SUCCESS
        return DelistTaskResponse(run_id=run_id, status=status, result=result)

    background.add_task(_job)
    return DelistTaskResponse(
        run_id=run_id,
        status=RunStatus.RUNNING,
        message="下架任务已在后台启动，请通过 GET /api/runs/{run_id} 查询进度",
    )

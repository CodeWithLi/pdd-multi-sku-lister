"""Task trigger APIs."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException

from pdd_agent.api.schemas.tasks import (
    BatchRunItem,
    BatchTaskResponse,
    CampaignLimitedTimeSetupRequest,
    CampaignTaskResponse,
    DelistBatchTaskRequest,
    DelistTaskRequest,
    DelistTaskResponse,
    ListingBatchTaskRequest,
    ListingTaskRequest,
    ListingTaskResponse,
    PlanRequest,
    PlanResponse,
    RetryListingItemRequest,
)
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.api.services.task_queue import enqueue_delist_task, enqueue_listing_task
from pdd_agent.api.services.task_runner import (
    create_campaign_run,
    create_delist_run,
    create_listing_run,
    execute_campaign_limited_time_setup,
    execute_delist,
    execute_listing,
    plan_tasks,
)
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.session import is_database_available
from pdd_agent.db.repositories import cancel_queued_task_by_run_id
from pdd_agent.domain.enums import AgentKind, RunStatus
from pdd_agent.storage import TaskRunStore

router = APIRouter(prefix="/tasks", tags=["tasks"])
_ACTIVE_CAMPAIGN_RUNS: dict[str, str] = {}


def _dedupe_account_ids(account_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(a.strip() for a in account_ids if a and a.strip()))


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def _batch_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _resolve_batch_concurrency(requested: int | None) -> int:
    configured = load_yaml_settings().batch.max_concurrent_stores
    value = requested or configured or 3
    return max(1, min(5, value))


def _resolve_batch_delay(min_requested: int | None, max_requested: int | None) -> tuple[int, int]:
    batch = load_yaml_settings().batch
    min_seconds = (
        min_requested if min_requested is not None else batch.store_start_delay_min_seconds
    )
    max_seconds = (
        max_requested if max_requested is not None else batch.store_start_delay_max_seconds
    )
    min_seconds = max(0, min(3600, min_seconds))
    max_seconds = max(0, min(3600, max_seconds))
    if max_seconds < min_seconds:
        max_seconds = min_seconds
    return min_seconds, max_seconds


def _require_queue_available() -> None:
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL task queue unavailable")


def _mark_queued(run_id: str) -> None:
    TaskRunStore().update_status(run_id, RunStatus.PENDING, "queued")


def _find_running_campaign_run(account_id: str) -> str:
    active_run_id = _ACTIVE_CAMPAIGN_RUNS.get(account_id)
    if active_run_id:
        return active_run_id

    store = TaskRunStore()
    started_from = datetime.now() - timedelta(minutes=30)
    records, _ = store.search_runs(
        page=1,
        page_size=20,
        account_id=account_id,
        agent=AgentKind.CAMPAIGN.value,
        started_from=started_from,
    )
    for record in records:
        if record.status in {RunStatus.PENDING, RunStatus.RUNNING}:
            return record.run_id
    return ""


async def _execute_campaign_limited_time_setup_guarded(**kwargs):
    account_id = str(kwargs.get("account_id") or "")
    run_id = str(kwargs.get("run_id") or "")
    try:
        return await execute_campaign_limited_time_setup(**kwargs)
    finally:
        if account_id and _ACTIVE_CAMPAIGN_RUNS.get(account_id) == run_id:
            _ACTIVE_CAMPAIGN_RUNS.pop(account_id, None)


@router.post("/plan", response_model=PlanResponse)
def tasks_plan(body: PlanRequest):
    return plan_tasks(body.message)


@router.post("/cancel/{run_id}", response_model=ListingTaskResponse)
def cancel_task(run_id: str):
    if not cancel_queued_task_by_run_id(run_id):
        raise HTTPException(status_code=409, detail="task is not queued or does not exist")
    TaskRunStore().update_status(run_id, RunStatus.CANCELED, "canceled by user")
    return ListingTaskResponse(
        run_id=run_id,
        status=RunStatus.CANCELED,
        message="task canceled",
    )


@router.post("/listing", response_model=ListingTaskResponse)
async def tasks_listing(body: ListingTaskRequest):
    settings = load_yaml_settings()
    if not get_account_or_none(body.account_id, settings):
        raise HTTPException(status_code=404, detail=f"unknown account: {body.account_id}")

    run_id = create_listing_run(body.account_id)
    codes = body.product_codes

    if body.dry_run or not body.background:
        result = await execute_listing(
            run_id=run_id,
            account_id=body.account_id,
            product_codes=codes,
            dry_run=body.dry_run,
            category_keyword=body.category_keyword,
            platform_listing_code=body.platform_listing_code,
        )
        record = TaskRunStore().load(run_id)
        status = record.status if record else RunStatus.SUCCESS
        return ListingTaskResponse(run_id=run_id, status=status, result=result)

    _require_queue_available()
    _mark_queued(run_id)
    enqueue_listing_task(
        run_id=run_id,
        account_id=body.account_id,
        product_codes=codes,
        dry_run=body.dry_run,
        category_keyword=body.category_keyword,
        platform_listing_code=body.platform_listing_code,
        scheduled_at=datetime.now(),
    )
    return ListingTaskResponse(
        run_id=run_id,
        status=RunStatus.PENDING,
        message="listing task queued; query /api/runs/{run_id} for progress",
    )


@router.post("/listing/retry-item/{source_run_id}", response_model=ListingTaskResponse)
async def retry_listing_item(source_run_id: str, body: RetryListingItemRequest):
    _require_queue_available()
    source = TaskRunStore().load(source_run_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"run not found: {source_run_id}")
    if source.agent.value != "listing":
        raise HTTPException(status_code=422, detail="source run is not a listing run")

    item = _find_listing_item(source.result, body)
    if not item:
        raise HTTPException(status_code=404, detail=f"listing item not found: {body.listing_label}")

    product_code = body.product_code or str(item.get("product_code") or "").strip()
    image_set = body.image_set if body.image_set != "" else str(item.get("image_set") or "")
    if not product_code:
        product_code = body.listing_label.split("/", 1)[0]

    settings = load_yaml_settings()
    if not get_account_or_none(source.account_id, settings):
        raise HTTPException(status_code=404, detail=f"unknown account: {source.account_id}")

    run_id = create_listing_run(source.account_id)
    _mark_queued(run_id)
    enqueue_listing_task(
        run_id=run_id,
        account_id=source.account_id,
        product_codes=[product_code],
        dry_run=False,
        category_keyword=body.category_keyword or settings.listing.category_keyword,
        platform_listing_code=body.platform_listing_code or str(item.get("merchant_code") or ""),
        scheduled_at=datetime.now(),
        retry_item={
            "source_run_id": source_run_id,
            "listing_label": body.listing_label,
            "product_code": product_code,
            "image_set": image_set,
        },
    )
    return ListingTaskResponse(
        run_id=run_id,
        status=RunStatus.PENDING,
        message=f"retry queued for {body.listing_label}",
    )


@router.post("/listing/batch", response_model=BatchTaskResponse)
async def tasks_listing_batch(body: ListingBatchTaskRequest):
    _require_queue_available()
    settings = load_yaml_settings()
    account_ids = _dedupe_account_ids(body.account_ids)
    if not account_ids:
        raise HTTPException(status_code=422, detail="account_ids cannot be empty")

    missing = [a for a in account_ids if not get_account_or_none(a, settings)]
    if missing:
        raise HTTPException(status_code=404, detail=f"unknown accounts: {', '.join(missing)}")

    max_concurrent = _resolve_batch_concurrency(body.max_concurrent_stores)
    delay_range = _resolve_batch_delay(
        body.store_start_delay_min_seconds,
        body.store_start_delay_max_seconds,
    )
    runs: list[BatchRunItem] = []
    scheduled_at = datetime.now()

    for index, account_id in enumerate(account_ids):
        if index > 0 and delay_range[1] > 0:
            scheduled_at += timedelta(seconds=random.randint(delay_range[0], delay_range[1]))
        run_id = create_listing_run(account_id)
        _mark_queued(run_id)
        enqueue_listing_task(
            run_id=run_id,
            account_id=account_id,
            product_codes=body.product_codes,
            dry_run=body.dry_run,
            category_keyword=body.category_keyword,
            platform_listing_code=body.platform_listing_code,
            scheduled_at=scheduled_at,
        )
        runs.append(BatchRunItem(account_id=account_id, run_id=run_id, status=RunStatus.PENDING))

    return BatchTaskResponse(
        batch_id=_batch_id(),
        status=RunStatus.PENDING,
        total=len(runs),
        max_concurrent_stores=max_concurrent,
        store_start_delay_min_seconds=delay_range[0],
        store_start_delay_max_seconds=delay_range[1],
        runs=runs,
        message=(
            f"batch listing queued: {len(runs)} stores, concurrency {max_concurrent}, "
            f"start delay {delay_range[0]}-{delay_range[1]}s"
        ),
    )


def _find_listing_item(result: dict, body: RetryListingItemRequest) -> dict | None:
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        if item.get("listing_label") != body.listing_label:
            continue
        if body.product_code and item.get("product_code") != body.product_code:
            continue
        if body.image_set != "" and item.get("image_set", "") != body.image_set:
            continue
        return item
    return None


@router.post("/delist", response_model=DelistTaskResponse)
async def tasks_delist(body: DelistTaskRequest):
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

    if not body.background:
        result = await execute_delist(
            run_id=run_id,
            account_id=body.account_id,
            delist_params=params,
        )
        record = TaskRunStore().load(run_id)
        status = record.status if record else RunStatus.SUCCESS
        return DelistTaskResponse(run_id=run_id, status=status, result=result)

    _require_queue_available()
    _mark_queued(run_id)
    enqueue_delist_task(
        run_id=run_id,
        account_id=body.account_id,
        dry_run=body.dry_run,
        delist_params=params,
        scheduled_at=datetime.now(),
    )
    return DelistTaskResponse(
        run_id=run_id,
        status=RunStatus.PENDING,
        message="delist task queued; query /api/runs/{run_id} for progress",
    )


@router.post("/delist/batch", response_model=BatchTaskResponse)
async def tasks_delist_batch(body: DelistBatchTaskRequest):
    _require_queue_available()
    settings = load_yaml_settings()
    account_ids = _dedupe_account_ids(body.account_ids)
    if not account_ids:
        raise HTTPException(status_code=422, detail="account_ids cannot be empty")

    missing = [a for a in account_ids if not get_account_or_none(a, settings)]
    if missing:
        raise HTTPException(status_code=404, detail=f"unknown accounts: {', '.join(missing)}")

    max_concurrent = _resolve_batch_concurrency(body.max_concurrent_stores)
    delay_range = _resolve_batch_delay(
        body.store_start_delay_min_seconds,
        body.store_start_delay_max_seconds,
    )
    params = {
        "min_created_after": body.min_created_after or settings.delist.min_created_after,
        "merchant_code_contains": body.merchant_code_contains or settings.delist.merchant_code_contains,
        "max_delist_per_run": body.max_delist_per_run,
    }
    if body.dry_run is not None:
        params["dry_run"] = body.dry_run

    runs: list[BatchRunItem] = []
    scheduled_at = datetime.now()
    for index, account_id in enumerate(account_ids):
        if index > 0 and delay_range[1] > 0:
            scheduled_at += timedelta(seconds=random.randint(delay_range[0], delay_range[1]))
        run_id = create_delist_run(account_id)
        _mark_queued(run_id)
        enqueue_delist_task(
            run_id=run_id,
            account_id=account_id,
            dry_run=body.dry_run,
            delist_params=params,
            scheduled_at=scheduled_at,
        )
        runs.append(BatchRunItem(account_id=account_id, run_id=run_id, status=RunStatus.PENDING))

    return BatchTaskResponse(
        batch_id=_batch_id(),
        status=RunStatus.PENDING,
        total=len(runs),
        max_concurrent_stores=max_concurrent,
        store_start_delay_min_seconds=delay_range[0],
        store_start_delay_max_seconds=delay_range[1],
        runs=runs,
        message=(
            f"batch delist queued: {len(runs)} stores, concurrency {max_concurrent}, "
            f"start delay {delay_range[0]}-{delay_range[1]}s"
        ),
    )


@router.post("/campaign/limited-time-setup", response_model=CampaignTaskResponse)
async def campaign_limited_time_setup(
    body: CampaignLimitedTimeSetupRequest,
    background: BackgroundTasks,
):
    settings = load_yaml_settings()
    if not get_account_or_none(body.account_id, settings):
        raise HTTPException(status_code=404, detail=f"unknown account: {body.account_id}")
    pdd_product_ids = _dedupe_strings(body.pdd_product_ids)
    published_mapping_ids = _dedupe_strings(body.published_mapping_ids)
    if not pdd_product_ids:
        raise HTTPException(status_code=422, detail="pdd_product_ids cannot be empty")

    running_run_id = _find_running_campaign_run(body.account_id)
    if running_run_id:
        return CampaignTaskResponse(
            run_id=running_run_id,
            status=RunStatus.RUNNING,
            message="该店铺已有活动任务正在执行，已复用当前运行记录；请等待完成后再启动新的活动任务。",
        )

    run_id = create_campaign_run(body.account_id)
    _ACTIVE_CAMPAIGN_RUNS[body.account_id] = run_id
    background.add_task(
        _execute_campaign_limited_time_setup_guarded,
        run_id=run_id,
        account_id=body.account_id,
        pdd_product_ids=pdd_product_ids,
        published_mapping_ids=published_mapping_ids,
    )
    return CampaignTaskResponse(
        run_id=run_id,
        status=RunStatus.RUNNING,
        message="限时限量购活动设置任务已启动；完成后在操作记录查看结果",
    )

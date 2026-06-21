"""整合链路 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.pipelines import (
    IntegratedPipelineBatchResponse,
    IntegratedPipelineBatchStartRequest,
    IntegratedPipelineListResponse,
    IntegratedPipelineResponse,
    IntegratedPipelineStartRequest,
)
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.api.services.pipeline_service import (
    cancel_integrated_pipeline,
    get_pipeline,
    list_pipelines,
    start_integrated_pipeline,
    start_integrated_pipeline_batch,
)
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _dedupe_account_ids(account_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(a.strip() for a in account_ids if a and a.strip()))


def _normalize_batch_items(body: IntegratedPipelineBatchStartRequest) -> list[dict]:
    if body.items:
        return [
            {
                "account_id": item.account_id.strip(),
                "product_codes": list(dict.fromkeys(c.strip() for c in item.product_codes if c.strip())),
            }
            for item in body.items
        ]
    account_ids = _dedupe_account_ids(body.account_ids)
    product_codes = list(dict.fromkeys(c.strip() for c in body.product_codes if c.strip()))
    return [{"account_id": account_id, "product_codes": product_codes} for account_id in account_ids]


@router.post("/integrated", response_model=IntegratedPipelineResponse)
def start_integrated(body: IntegratedPipelineStartRequest):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用，无法创建整合链路")
    if not get_account_or_none(body.account_id):
        raise HTTPException(status_code=404, detail=f"unknown account: {body.account_id}")
    try:
        data = start_integrated_pipeline(
            account_id=body.account_id,
            product_codes=body.product_codes,
            activity_id=body.activity_id,
            activity_ids=body.activity_ids,
            category_keyword=body.category_keyword,
            auto_promotion=body.auto_promotion,
            auto_limited_time_setup=body.auto_limited_time_setup,
            continue_after_limited_time_failure=body.continue_after_limited_time_failure,
            continue_after_activity_failure=body.continue_after_activity_failure,
            activity_delay_hours=body.activity_delay_hours,
            demo_mode=body.demo_mode,
            platform_listing_code=body.platform_listing_code,
            slot_alignment_test=body.slot_alignment_test,
            skip_listing=body.skip_listing,
            listing_skip_selectors=body.listing_skip_selectors,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IntegratedPipelineResponse(**data)


@router.post("/integrated/batch", response_model=IntegratedPipelineBatchResponse)
def start_integrated_batch(body: IntegratedPipelineBatchStartRequest):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用，无法创建整合链路")
    settings = load_yaml_settings()
    try:
        items = _normalize_batch_items(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not items:
        raise HTTPException(status_code=422, detail="items cannot be empty")

    for item in items:
        account_id = str(item.get("account_id") or "").strip()
        if not account_id:
            raise HTTPException(status_code=422, detail="account_id is required for each item")
        if not get_account_or_none(account_id, settings):
            raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")
        if not item.get("product_codes"):
            raise HTTPException(status_code=422, detail=f"product_codes is required for account: {account_id}")

    try:
        data = start_integrated_pipeline_batch(
            items=items,
            activity_id=body.activity_id,
            activity_ids=body.activity_ids,
            category_keyword=body.category_keyword,
            auto_promotion=body.auto_promotion,
            auto_limited_time_setup=body.auto_limited_time_setup,
            continue_after_limited_time_failure=body.continue_after_limited_time_failure,
            continue_after_activity_failure=body.continue_after_activity_failure,
            activity_delay_hours=body.activity_delay_hours,
            demo_mode=body.demo_mode,
            platform_listing_code=body.platform_listing_code,
            slot_alignment_test=body.slot_alignment_test,
            skip_listing=body.skip_listing,
            listing_skip_selectors=body.listing_skip_selectors,
            store_start_delay_min_seconds=body.store_start_delay_min_seconds,
            store_start_delay_max_seconds=body.store_start_delay_max_seconds,
            max_concurrent_stores=body.max_concurrent_stores,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IntegratedPipelineBatchResponse(**data)


@router.get("/integrated", response_model=IntegratedPipelineListResponse)
def list_integrated(limit: int = 50, batch_id: str = ""):
    if not is_database_available():
        return IntegratedPipelineListResponse(items=[], total=0)
    data = list_pipelines(limit=limit, batch_id=batch_id)
    return IntegratedPipelineListResponse(
        items=[IntegratedPipelineResponse(**item) for item in data.get("items") or []],
        total=int(data.get("total") or 0),
    )


@router.get("/integrated/{pipeline_id}", response_model=IntegratedPipelineResponse)
def get_integrated(pipeline_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    data = get_pipeline(pipeline_id)
    if not data:
        raise HTTPException(status_code=404, detail="pipeline not found")
    return IntegratedPipelineResponse(**data)


@router.post("/integrated/{pipeline_id}/cancel", response_model=IntegratedPipelineResponse)
def cancel_integrated(pipeline_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    try:
        data = cancel_integrated_pipeline(pipeline_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "pipeline not found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return IntegratedPipelineResponse(**data)

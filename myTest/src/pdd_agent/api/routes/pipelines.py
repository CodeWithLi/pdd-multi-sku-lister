"""整合链路 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.pipelines import (
    IntegratedPipelineListResponse,
    IntegratedPipelineResponse,
    IntegratedPipelineStartRequest,
)
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.api.services.pipeline_service import get_pipeline, list_pipelines, start_integrated_pipeline
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


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
            category_keyword=body.category_keyword,
            auto_promotion=body.auto_promotion,
            activity_delay_hours=body.activity_delay_hours,
            demo_mode=body.demo_mode,
            platform_listing_code=body.platform_listing_code,
            slot_alignment_test=body.slot_alignment_test,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IntegratedPipelineResponse(**data)


@router.get("/integrated", response_model=IntegratedPipelineListResponse)
def list_integrated(limit: int = 50):
    if not is_database_available():
        return IntegratedPipelineListResponse(items=[], total=0)
    data = list_pipelines(limit=limit)
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

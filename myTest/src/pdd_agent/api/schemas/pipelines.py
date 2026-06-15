"""整合链路 API 模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IntegratedPipelineStartRequest(BaseModel):
    account_id: str
    product_codes: list[str] = Field(min_length=1)
    activity_id: str
    category_keyword: str = "玩偶"
    auto_promotion: bool = True
    activity_delay_hours: float = Field(default=24.0, ge=0)
    demo_mode: bool = False
    platform_listing_code: str = ""
    slot_alignment_test: bool = False


class IntegratedPipelineStepInfo(BaseModel):
    key: str
    label: str
    status: str
    run_id: str = ""
    scheduled_at: datetime | None = None
    detail: str = ""


class IntegratedPipelineResponse(BaseModel):
    pipeline_id: str
    account_id: str
    status: str
    current_step: str
    product_codes: list[str]
    activity_id: str
    auto_promotion: bool
    activity_delay_hours: float
    demo_mode: bool
    slot_alignment_test: bool = False
    listing_run_id: str = ""
    campaign_run_id: str = ""
    traffic_run_id: str = ""
    pdd_product_ids: list[str] = []
    mapping_ids: list[str] = []
    scheduled_activity_at: datetime | None = None
    error: str = ""
    steps: list[IntegratedPipelineStepInfo] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IntegratedPipelineListResponse(BaseModel):
    items: list[IntegratedPipelineResponse]
    total: int

"""整合链路 API 模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


def _normalize_activity_ids(activity_id: str = "", activity_ids: list[str] | None = None) -> list[str]:
    ids = [str(item).strip() for item in (activity_ids or []) if str(item).strip()]
    if ids:
        return list(dict.fromkeys(ids))
    legacy = str(activity_id or "").strip()
    return [legacy] if legacy else []


class IntegratedPipelineStartRequest(BaseModel):
    account_id: str
    product_codes: list[str] = Field(min_length=1)
    activity_id: str = ""
    activity_ids: list[str] = Field(default_factory=list)
    category_keyword: str = "玩偶"
    auto_promotion: bool = True
    auto_limited_time_setup: bool = True
    continue_after_limited_time_failure: bool = False
    continue_after_activity_failure: bool = False
    activity_delay_hours: float = Field(default=24.0, ge=0)
    demo_mode: bool = False
    platform_listing_code: str = ""
    slot_alignment_test: bool = True
    skip_listing: bool = False
    listing_skip_selectors: list[str] = Field(default_factory=list)
    material_source: str = ""

    @model_validator(mode="after")
    def validate_activity_ids(self) -> "IntegratedPipelineStartRequest":
        normalized = _normalize_activity_ids(self.activity_id, self.activity_ids)
        if not normalized:
            raise ValueError("activity_ids is required")
        self.activity_ids = normalized
        self.activity_id = normalized[0]
        return self


class IntegratedPipelineBatchItem(BaseModel):
    account_id: str
    product_codes: list[str] = Field(min_length=1)


class IntegratedPipelineBatchStartRequest(BaseModel):
    activity_id: str = ""
    activity_ids: list[str] = Field(default_factory=list)
    category_keyword: str = "玩偶"
    auto_promotion: bool = True
    auto_limited_time_setup: bool = True
    continue_after_limited_time_failure: bool = False
    continue_after_activity_failure: bool = False
    activity_delay_hours: float = Field(default=24.0, ge=0)
    demo_mode: bool = False
    platform_listing_code: str = ""
    slot_alignment_test: bool = True
    skip_listing: bool = False
    listing_skip_selectors: list[str] = Field(default_factory=list)
    material_source: str = ""
    account_ids: list[str] = Field(default_factory=list)
    product_codes: list[str] = Field(default_factory=list)
    items: list[IntegratedPipelineBatchItem] = Field(default_factory=list)
    store_start_delay_min_seconds: int | None = Field(default=None, ge=0, le=3600)
    store_start_delay_max_seconds: int | None = Field(default=None, ge=0, le=3600)
    max_concurrent_stores: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def validate_batch_items(self) -> "IntegratedPipelineBatchStartRequest":
        normalized = _normalize_activity_ids(self.activity_id, self.activity_ids)
        if not normalized:
            raise ValueError("activity_ids is required")
        self.activity_ids = normalized
        self.activity_id = normalized[0]
        if self.items:
            return self
        account_ids = [a.strip() for a in self.account_ids if a and a.strip()]
        product_codes = [c.strip() for c in self.product_codes if c and c.strip()]
        if not account_ids:
            raise ValueError("account_ids or items is required")
        if not product_codes:
            raise ValueError("product_codes is required when using account_ids")
        return self


class IntegratedPipelineStepInfo(BaseModel):
    key: str
    label: str
    status: str
    run_id: str = ""
    scheduled_at: datetime | None = None
    detail: str = ""


class IntegratedPipelineCampaignResult(BaseModel):
    activity_id: str
    run_id: str = ""
    success: bool = False
    skipped: bool = False
    error: str = ""
    summary: str = ""


class IntegratedPipelineResponse(BaseModel):
    pipeline_id: str
    account_id: str
    status: str
    current_step: str
    product_codes: list[str]
    activity_id: str
    activity_ids: list[str] = Field(default_factory=list)
    auto_promotion: bool
    auto_limited_time_setup: bool = True
    continue_after_limited_time_failure: bool = False
    continue_after_activity_failure: bool = False
    limited_time_outcome: str = ""
    limited_time_skip_reason: str = ""
    activity_delay_hours: float
    demo_mode: bool
    slot_alignment_test: bool = False
    batch_id: str = ""
    activity_jitter_seconds: int = 0
    listing_run_id: str = ""
    campaign_run_id: str = ""
    traffic_run_id: str = ""
    pdd_product_ids: list[str] = []
    mapping_ids: list[str] = []
    scheduled_activity_at: datetime | None = None
    error: str = ""
    campaign_outcome: str = ""
    campaign_skip_reason: str = ""
    listing_outcome: str = ""
    listing_skip_reason: str = ""
    campaign_results: list[IntegratedPipelineCampaignResult] = Field(default_factory=list)
    steps: list[IntegratedPipelineStepInfo] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IntegratedPipelineBatchRunItem(BaseModel):
    account_id: str
    pipeline_id: str
    listing_run_id: str
    listing_scheduled_at: datetime


class IntegratedPipelineBatchResponse(BaseModel):
    batch_id: str
    total: int
    max_concurrent_stores: int
    store_start_delay_min_seconds: int
    store_start_delay_max_seconds: int
    pipelines: list[IntegratedPipelineBatchRunItem]
    message: str


class IntegratedPipelineListResponse(BaseModel):
    items: list[IntegratedPipelineResponse]
    total: int
    page: int = 1
    page_size: int = 10


class PipelineExcelFallbackOut(BaseModel):
    enabled: bool


class PipelineExcelFallbackUpdateIn(BaseModel):
    enabled: bool

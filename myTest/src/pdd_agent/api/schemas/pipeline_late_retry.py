"""整合链路 — 等活动期间补跑失败项 API 模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PipelineLateRetryStartRequest(BaseModel):
    selectors: list[str] = Field(default_factory=list)
    deadline_buffer_minutes: int | None = Field(default=None, ge=0, le=1440)


class PipelineLateRetryEligibilityOut(BaseModel):
    eligible: bool = False
    reason: str = ""
    failed_selectors: list[str] = Field(default_factory=list)
    failed_count: int = 0
    minutes_remaining: float | None = None
    required_buffer_minutes: int = 30
    activity_deadline_at: str = ""


class PipelineLateRetryStateOut(BaseModel):
    enabled: bool = False
    phase: str = "idle"
    outcome: str = ""
    outcome_detail: str = ""
    selectors: list[str] = Field(default_factory=list)
    succeeded_selectors: list[str] = Field(default_factory=list)
    failed_selectors: list[str] = Field(default_factory=list)
    expired_selectors: list[str] = Field(default_factory=list)
    listing_run_id: str = ""
    limited_time_run_id: str = ""
    activity_deadline_at: str = ""
    minutes_remaining: float | None = None
    merged_pdd_count: int = 0
    eligible: bool | None = None
    eligibility: PipelineLateRetryEligibilityOut | None = None


class PipelineLateRetryStartResponse(BaseModel):
    pipeline_id: str = ""
    listing_run_id: str = ""
    selector_count: int = 0
    selectors: list[str] = Field(default_factory=list)
    activity_deadline_at: str = ""
    late_retry: PipelineLateRetryStateOut = Field(default_factory=PipelineLateRetryStateOut)

"""整合链路 — 分批限时限量购失败重跑 API 模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PipelineBatchLimitedTimeRetryEligibilityOut(BaseModel):
    eligible: bool = False
    reason: str = ""
    batch_index: int = 0
    retry_count: int = 0
    pdd_product_ids: list[str] = Field(default_factory=list)


class PipelineBatchLimitedTimeRetryStateOut(BaseModel):
    enabled: bool = False
    phase: str = "idle"
    outcome: str = ""
    outcome_detail: str = ""
    active_batch_index: int | None = None
    pending_batch_indices: list[int] = Field(default_factory=list)
    completed_batch_indices: list[int] = Field(default_factory=list)
    limited_time_run_id: str = ""
    last_success_finished_at: str = ""
    merged_pdd_count: int = 0


class PipelineBatchLimitedTimeRetryStartRequest(BaseModel):
    batch_index: int = Field(..., ge=0)


class PipelineBatchLimitedTimeRetryStartResponse(BaseModel):
    pipeline_id: str = ""
    batch_index: int = 0
    limited_time_run_id: str = ""
    retry_count: int = 0
    pdd_product_ids: list[str] = Field(default_factory=list)
    queued: bool = False
    batch_limited_time_retry: PipelineBatchLimitedTimeRetryStateOut = Field(
        default_factory=PipelineBatchLimitedTimeRetryStateOut
    )

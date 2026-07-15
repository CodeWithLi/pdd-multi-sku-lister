"""失败日志循环上架轮询 API schemas。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class PddFailureCycleRelistActionOut(BaseModel):
    at: str = ""
    record_id: str = ""
    merchant_code: str = ""
    account_name: str = ""
    failure_reason: str = ""
    status: str = ""
    message: str = ""
    pipeline_id: str = ""
    trigger_source: str = ""


class PddFailureCycleRelistPollLogOut(BaseModel):
    poll_log_id: str = ""
    polled_at: str = ""
    candidate_total: int = 0
    new_count: int = 0
    fetch_mode: str = ""
    fetch_page_size: int = 0
    table_id: str = ""
    table_name: str = ""
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    new_candidates: list[dict[str, Any]] = Field(default_factory=list)


class PddFailureCycleRelistPollLogListResponse(BaseModel):
    ok: bool = True
    total: int = 0
    items: list[PddFailureCycleRelistPollLogOut] = Field(default_factory=list)


class PddFailureCycleRelistWatchOut(BaseModel):
    enabled: bool = False
    poll_seconds: int = 60
    completed_statuses: list[str] = Field(default_factory=list)
    exclude_failure_reason_contains: list[str] = Field(default_factory=list)
    scheduler_running: bool = False
    last_poll_at: str = ""
    last_error: str = ""
    candidate_total: int = 0
    new_count: int = 0
    sequential_staged_enabled: bool = False
    sequential_scheduler_running: bool = False
    sequential_last_tick_at: str = ""
    sequential_last_error: str = ""
    sequential_batch_active: bool = False
    sequential_batch_status: str = ""
    sequential_activity_delay_minutes: int = 5
    attach_source_pipeline_enabled: bool = False
    capture_pipeline_id_enabled: bool = False
    cycle_relist_blocker_pipeline_id: str = ""
    cycle_relist_blocker_stale: bool = False
    cycle_relist_blocker_age_hours: float = 0
    recent_actions: list[PddFailureCycleRelistActionOut] = Field(default_factory=list)


class PddFailureCycleRelistWatchUpdateIn(BaseModel):
    enabled: bool = False
    poll_seconds: int = Field(default=60, ge=10, le=3600)
    completed_statuses: list[str] = Field(
        default_factory=lambda: ["已结束", "已处理完成"],
    )
    exclude_failure_reason_contains: list[str] = Field(default_factory=list)
    sequential_staged_enabled: bool = False
    sequential_activity_delay_minutes: int = Field(default=5, ge=0, le=10080)
    attach_source_pipeline_enabled: bool = False
    capture_pipeline_id_enabled: bool = False

    @field_validator("exclude_failure_reason_contains", mode="before")
    @classmethod
    def _normalize_exclude_failure_reason_contains(cls, value: Any) -> list[str]:
        from pdd_agent.integrations.feishu.failure_cycle_relist_exclude import (
            normalize_exclude_failure_reason_phrases,
        )

        return normalize_exclude_failure_reason_phrases(value)


class PddFailureCycleRelistTriggerIn(BaseModel):
    record_id: str = Field(min_length=1)
    merchant_code: str = ""
    account_name: str = ""
    account_id: str = ""
    report_platform: str = ""


class PddFailureCycleRelistTriggerOut(BaseModel):
    ok: bool
    skipped: bool = False
    reason: str = ""
    error: str = ""
    record_id: str = ""
    merchant_code: str = ""
    account_name: str = ""
    account_id: str = ""
    pipeline_id: str = ""
    product_codes: list[str] = Field(default_factory=list)
    claim: dict[str, Any] = Field(default_factory=dict)


class PddFailureCycleRelistClaimIn(BaseModel):
    record_id: str = Field(min_length=1)
    merchant_code: str = ""
    account_name: str = ""
    account_id: str = ""


class PddFailureCycleRelistReleaseIn(BaseModel):
    record_id: str = Field(min_length=1)
    final_value: str = ""
    update_feishu: bool = True


class PddFailureCycleRelistClaimOut(BaseModel):
    ok: bool
    claimed: bool = False
    record_id: str = ""
    reason: str = ""
    error: str = ""
    redis_claimed: bool = False
    feishu_updated: bool = False
    placeholder: str = ""
    redis_payload: dict[str, Any] | None = None


class PddFailureCycleRelistCandidateOut(BaseModel):
    record_id: str
    merchant_code: str = ""
    account_name: str = ""
    account_id: str = ""
    report_platform: str = ""
    record_type: str = ""
    failure_reason: str = ""
    system_reason: str = ""
    source_pipeline_id: str = Field(
        default="",
        description="从失败日志「系统原因」切割出的原整合链路 id（[pipeline:xxx]）",
    )
    process_status: str = ""
    cycle_relist: str = ""
    processor: str = ""
    processed_at: str = ""
    date: str = ""
    action_status: str = ""
    action_message: str = ""
    action_at: str = ""
    pipeline_id: str = Field(
        default="",
        description="本轮循环上架新启动的整合链路 id",
    )


class PddFailureCycleRelistCandidateListResponse(BaseModel):
    ok: bool
    error: str = ""
    total: int = 0
    items: list[PddFailureCycleRelistCandidateOut] = Field(default_factory=list)
    new_items: list[PddFailureCycleRelistCandidateOut] = Field(default_factory=list)
    table_id: str = ""
    table_name: str = ""


class PddFailureCycleRelistPollResponse(BaseModel):
    ok: bool
    skipped: bool = False
    reason: str = ""
    error: str = ""
    polled_at: str = ""
    total: int = 0
    new_count: int = 0
    new_items: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    pipeline_triggers: list[dict[str, Any]] = Field(default_factory=list)


class FailureSequentialJobOut(BaseModel):
    job_id: str
    batch_id: str
    feishu_record_id: str
    merchant_code: str = ""
    account_id: str = ""
    account_name: str = ""
    failure_reason: str = ""
    current_phase: str = ""
    overall_status: str = ""
    pdd_product_id: str = ""
    listing_status: str = ""
    listing_error: str = ""
    limited_time_status: str = ""
    limited_time_error: str = ""
    limited_time_completed_at: str = ""
    activity_618_status: str = ""
    activity_618_error: str = ""
    activity_discount_status: str = ""
    activity_discount_error: str = ""
    promotion_status: str = ""
    promotion_error: str = ""
    updated_at: str = ""


class FailureSequentialJobListResponse(BaseModel):
    ok: bool = True
    total: int = 0
    batch_active: bool = False
    batch: dict[str, Any] = Field(default_factory=dict)
    items: list[FailureSequentialJobOut] = Field(default_factory=list)


class FailureSequentialTickResponse(BaseModel):
    ok: bool = True
    summary: dict[str, Any] = Field(default_factory=dict)


class FailureSequentialStuckStageOut(BaseModel):
    stage: str = ""
    label: str = ""
    run_id: str = ""
    reason: str = ""


class FailureSequentialStuckJobOut(BaseModel):
    job_id: str
    batch_id: str = ""
    merchant_code: str = ""
    account_name: str = ""
    updated_at: str = ""
    stuck_stages: list[FailureSequentialStuckStageOut] = Field(default_factory=list)


class FailureSequentialStuckListResponse(BaseModel):
    ok: bool = True
    total: int = 0
    items: list[FailureSequentialStuckJobOut] = Field(default_factory=list)


class FailureSequentialResetStuckResponse(BaseModel):
    ok: bool = True
    reset_count: int = 0
    items: list[FailureSequentialStuckJobOut] = Field(default_factory=list)


class PddFailureCycleRelistDismissBlockerIn(BaseModel):
    pipeline_id: str = Field(
        default="",
        description="留空则解除当前检测到的阻塞链路",
    )


class PddFailureCycleRelistDismissBlockerOut(BaseModel):
    ok: bool = True
    pipeline_id: str = ""
    dismissed_records: int = 0
    stale: bool = False
    message: str = ""
    error: str = ""


class PddFailureCycleRelistClearRecentActionsOut(BaseModel):
    ok: bool = True
    cleared_memory: int = 0
    cleared_db: int = 0
    message: str = ""
    error: str = ""

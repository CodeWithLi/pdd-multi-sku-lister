"""失败日志循环上架轮询 API schemas。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    exclude_failure_reason_contains: str = ""
    scheduler_running: bool = False
    last_poll_at: str = ""
    last_error: str = ""
    candidate_total: int = 0
    new_count: int = 0
    recent_actions: list[PddFailureCycleRelistActionOut] = Field(default_factory=list)


class PddFailureCycleRelistWatchUpdateIn(BaseModel):
    enabled: bool = False
    poll_seconds: int = Field(default=60, ge=10, le=3600)
    completed_statuses: list[str] = Field(
        default_factory=lambda: ["已结束", "已处理完成"],
    )
    exclude_failure_reason_contains: str = ""


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
    process_status: str = ""
    cycle_relist: str = ""
    processor: str = ""
    processed_at: str = ""
    date: str = ""
    action_status: str = ""
    action_message: str = ""
    action_at: str = ""
    pipeline_id: str = ""


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

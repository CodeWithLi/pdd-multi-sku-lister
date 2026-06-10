"""任务 / 运行记录 API 模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from pdd_agent.domain.enums import AgentKind, RunStatus, TaskPhase
from pdd_agent.domain.models import PlannedTask


class PlanRequest(BaseModel):
    message: str = Field(..., min_length=1, description="自然语言指令")


class PlanResponse(BaseModel):
    plan_summary: str = ""
    planned_tasks: list[dict[str, Any]] = Field(default_factory=list)


class ListingTaskRequest(BaseModel):
    account_id: str
    product_codes: list[str] = Field(default_factory=list)
    platform_listing_code: str = ""
    dry_run: bool = False
    category_keyword: str = "玩偶"
    background: bool = True  # False 时同步等待（仅建议 dry_run 使用）


class ListingTaskResponse(BaseModel):
    run_id: str
    status: RunStatus
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)


class RetryListingItemRequest(BaseModel):
    listing_label: str = Field(..., min_length=1)
    product_code: str = ""
    image_set: str = ""
    platform_listing_code: str = ""
    category_keyword: str = "玩偶"


class ListingBatchTaskRequest(BaseModel):
    account_ids: list[str] = Field(..., min_length=1)
    product_codes: list[str] = Field(default_factory=list)
    platform_listing_code: str = ""
    dry_run: bool = False
    category_keyword: str = "玩偶"
    max_concurrent_stores: int | None = Field(default=None, ge=1, le=5)
    store_start_delay_min_seconds: int | None = Field(default=None, ge=0, le=3600)
    store_start_delay_max_seconds: int | None = Field(default=None, ge=0, le=3600)


class BatchRunItem(BaseModel):
    account_id: str
    run_id: str
    status: RunStatus
    message: str = ""


class BatchTaskResponse(BaseModel):
    batch_id: str
    status: RunStatus
    total: int
    max_concurrent_stores: int
    store_start_delay_min_seconds: int = 0
    store_start_delay_max_seconds: int = 0
    runs: list[BatchRunItem] = Field(default_factory=list)
    message: str = ""


class DelistTaskRequest(BaseModel):
    account_id: str
    dry_run: bool | None = None
    min_created_after: str = ""
    merchant_code_contains: str = ""
    max_delist_per_run: int = 50
    background: bool = True


class DelistTaskResponse(BaseModel):
    run_id: str
    status: RunStatus
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)


class DelistBatchTaskRequest(BaseModel):
    account_ids: list[str] = Field(..., min_length=1)
    dry_run: bool | None = None
    min_created_after: str = ""
    merchant_code_contains: str = ""
    max_delist_per_run: int = 50
    max_concurrent_stores: int | None = Field(default=None, ge=1, le=5)
    store_start_delay_min_seconds: int | None = Field(default=None, ge=0, le=3600)
    store_start_delay_max_seconds: int | None = Field(default=None, ge=0, le=3600)


class RunInterpretResponse(BaseModel):
    run_id: str
    interpretation: str
    llm_model: str = ""


class RunRecordOut(BaseModel):
    run_id: str
    agent: AgentKind
    account_id: str
    status: RunStatus
    phase: TaskPhase
    started_at: datetime
    finished_at: datetime | None = None
    message: str = ""
    listing_labels: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record) -> "RunRecordOut":
        return cls(
            run_id=record.run_id,
            agent=record.agent,
            account_id=record.account_id,
            status=record.status,
            phase=record.phase,
            started_at=record.started_at,
            finished_at=record.finished_at,
            message=record.message,
            listing_labels=record.listing_labels,
            result=record.result,
        )


class RunListResponse(BaseModel):
    items: list[RunRecordOut] = Field(default_factory=list)
    total: int
    page: int
    page_size: int

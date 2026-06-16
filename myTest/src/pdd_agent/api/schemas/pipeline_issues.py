"""整合链路报错 API 模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PipelineIssueOut(BaseModel):
    issue_id: str
    pipeline_id: str
    batch_id: str = ""
    account_id: str
    stage: str
    stage_label: str = ""
    chain_step: str = ""
    severity: str = "error"
    reason_code: str = ""
    title: str = ""
    message: str = ""
    error_text: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    run_id: str = ""
    activity_id: str = ""
    product_selector: str = ""
    source_location: str = ""
    created_at: datetime | None = None


class PipelineIssueListResponse(BaseModel):
    items: list[PipelineIssueOut]
    total: int
    page: int
    page_size: int


class PipelineIssueSummaryResponse(BaseModel):
    pipeline_id: str
    total: int
    error: int
    warning: int
    critical: int

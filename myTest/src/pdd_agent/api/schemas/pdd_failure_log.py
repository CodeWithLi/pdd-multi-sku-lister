"""发布失败日志（飞书）读取 API schemas。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PddFailureLogWorkflowOut(BaseModel):
    """处理状态（来自「处理状态镜像」列）。"""

    field_name: str = ""
    label: str = ""
    source: str = ""
    mirror_text: str = ""


class PddFailureLogRecordOut(BaseModel):
    record_id: str
    date: str = ""
    merchant_code: str = ""
    report_platform: str = ""
    account_name: str = ""
    record_type: str = ""
    failure_reason: str = ""
    system_reason: str = ""
    source_pipeline_id: str = ""
    publish_start: str = ""
    publish_end: str = ""
    duration_seconds: str = ""
    process_completed: PddFailureLogWorkflowOut
    cycle_relist: str = ""
    processor: str = ""
    processed_at: str = ""
    fields_raw: dict[str, Any] = Field(default_factory=dict)


class PddFailureLogFieldMetaOut(BaseModel):
    field_id: str = ""
    field_name: str = ""
    type: int = 0
    ui_type: str = ""


class PddFailureLogListResponse(BaseModel):
    ok: bool
    error: str = ""
    app_token: str = ""
    table_id: str = ""
    table_name: str = ""
    resolve_method: str = ""
    mirror_field_name: str = ""
    mirror_api_readable: bool = False
    total: int = 0
    items: list[PddFailureLogRecordOut] = Field(default_factory=list)
    field_meta: list[PddFailureLogFieldMetaOut] = Field(default_factory=list)
    table_name_candidates: list[str] = Field(default_factory=list)

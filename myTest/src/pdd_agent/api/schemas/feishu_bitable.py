"""Feishu bitable admin API schemas (tenant token mode)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FeishuBitableCreateAppIn(BaseModel):
    name: str = Field(default="新的多维表格")
    folder_token: str = ""
    time_zone: str = ""


class FeishuBitableCopyAppIn(BaseModel):
    source_app_token: str
    name: str = ""
    folder_token: str = ""
    without_content: bool = False
    time_zone: str = ""


class FeishuBitableCreateTableIn(BaseModel):
    app_token: str = ""
    name: str


class FeishuBitableUpdateTableIn(BaseModel):
    app_token: str = ""
    name: str


class FeishuBitableCreateFieldIn(BaseModel):
    app_token: str = ""
    table_id: str
    field_name: str
    type: int
    property: dict[str, Any] | None = None


class FeishuBitableUpdateFieldIn(BaseModel):
    app_token: str = ""
    table_id: str
    field_name: str
    type: int
    property: dict[str, Any] | None = None


class FeishuBitableBatchCreateRecordsIn(BaseModel):
    app_token: str = ""
    table_id: str
    records: list[dict[str, Any]]


class FeishuBitableBatchDeleteRecordsIn(BaseModel):
    app_token: str = ""
    table_id: str
    record_ids: list[str]


class FeishuBitableUpdateRecordIn(BaseModel):
    app_token: str = ""
    table_id: str
    fields: dict[str, Any]

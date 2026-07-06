"""企业微信 API 模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

WecomMsgType = Literal["text", "markdown", "markdown_v2", "raw"]


class WecomConfigOut(BaseModel):
    enabled: bool
    webhook_url: str = ""
    webhook_url_masked: str = ""
    webhook_configured: bool
    notify_on_listing_failed: bool = False
    notify_on_pipeline_failed: bool = False
    notify_on_commerce_queued: bool = False
    notify_on_commerce_dispatched: bool = False
    config_path: str = ""


class WecomConfigUpdateIn(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    notify_on_listing_failed: bool = False
    notify_on_pipeline_failed: bool = False
    notify_on_commerce_queued: bool = False
    notify_on_commerce_dispatched: bool = False


class WecomTestSendIn(BaseModel):
    msgtype: WecomMsgType = "text"
    content: str = "PDD Agent 测试消息"
    raw_payload: dict[str, Any] | None = None
    use_saved_webhook: bool = True
    webhook_url: str = ""


class WecomTestSendOut(BaseModel):
    ok: bool
    errcode: int = 0
    errmsg: str = ""
    payload_sent: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)


class WecomHealthOut(BaseModel):
    configured: bool
    enabled: bool
    webhook_configured: bool
    config_path: str = ""


class WecomDailyReportCommitOut(BaseModel):
    short_hash: str
    author: str
    committed_at: str
    subject: str
    body: str = ""
    file_count: int = 0


class WecomDailyReportPreviewOut(BaseModel):
    report_date: str
    repo_path: str
    commit_count: int
    progress_summary: str
    message: str
    commits: list[WecomDailyReportCommitOut] = Field(default_factory=list)

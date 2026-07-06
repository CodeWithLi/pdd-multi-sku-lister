"""企业微信 API 模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

WecomMsgType = Literal["text", "markdown", "markdown_v2", "raw"]
WecomDailyReportPlatform = Literal["pdd", "taobao"]


class WecomConfigOut(BaseModel):
    enabled: bool
    webhook_url: str = ""
    webhook_url_masked: str = ""
    webhook_configured: bool
    notify_on_listing_failed: bool = False
    notify_on_pipeline_failed: bool = False
    notify_on_commerce_queued: bool = False
    notify_on_commerce_dispatched: bool = False
    daily_report_schedule_enabled: bool = False
    daily_report_schedule_hour: int = 18
    daily_report_schedule_minute: int = 0
    daily_report_schedule_time: str = "18:00"
    daily_report_scheduler_running: bool = False
    daily_report_last_run_date: str = ""
    config_path: str = ""


class WecomConfigUpdateIn(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    notify_on_listing_failed: bool = False
    notify_on_pipeline_failed: bool = False
    notify_on_commerce_queued: bool = False
    notify_on_commerce_dispatched: bool = False
    daily_report_schedule_enabled: bool = False
    daily_report_schedule_hour: int = 18
    daily_report_schedule_minute: int = 0


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


class WecomDailyReportTriggerIn(BaseModel):
    platform: WecomDailyReportPlatform = "pdd"


class WecomDailyReportTriggerOut(BaseModel):
    ok: bool
    platform: WecomDailyReportPlatform = "pdd"
    message: str = ""


class WecomDailyContentOut(BaseModel):
    content_date: str = ""
    pdd_in_progress: str = ""
    taobao_netdisk_materials: str = ""
    taobao_in_progress: str = ""
    updated_at: str = ""
    database_available: bool = False


class WecomDailyContentUpdateIn(BaseModel):
    pdd_in_progress: str = ""
    taobao_netdisk_materials: str = ""
    taobao_in_progress: str = ""


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


class WecomDailyReportStoreOut(BaseModel):
    account_id: str
    shop_display_name: str
    count: int


class WecomDailyReportPreviewOut(BaseModel):
    platform: WecomDailyReportPlatform = "pdd"
    report_date: str
    repo_path: str = ""
    commit_count: int = 0
    progress_summary: str = ""
    store_progress: str = ""
    netdisk_materials: str = ""
    in_progress: str = ""
    listing_window_start: str = ""
    listing_window_end: str = ""
    store_summaries: list[WecomDailyReportStoreOut] = Field(default_factory=list)
    message: str
    commits: list[WecomDailyReportCommitOut] = Field(default_factory=list)

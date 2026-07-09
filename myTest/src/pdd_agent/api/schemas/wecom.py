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
    webhook_url_daily_report: str = ""
    webhook_url_daily_report_masked: str = ""
    webhook_daily_report_configured: bool = False
    notify_on_listing_failed: bool = False
    notify_on_pipeline_failed: bool = False
    notify_on_commerce_queued: bool = False
    notify_on_commerce_dispatched: bool = False
    daily_report_schedule_enabled: bool = False
    daily_report_schedule_hour: int = 18
    daily_report_schedule_minute: int = 0
    daily_report_schedule_use_saved_preview: bool = False
    daily_report_schedule_time: str = "18:00"
    daily_report_scheduler_running: bool = False
    daily_report_last_run_date: str = ""
    config_path: str = ""


class WecomConfigUpdateIn(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    webhook_url_daily_report: str = ""
    notify_on_listing_failed: bool = False
    notify_on_pipeline_failed: bool = False
    notify_on_commerce_queued: bool = False
    notify_on_commerce_dispatched: bool = False
    daily_report_schedule_enabled: bool = False
    daily_report_schedule_hour: int = 18
    daily_report_schedule_minute: int = 0
    daily_report_schedule_use_saved_preview: bool = False


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
    message: str = Field(
        default="",
        description="非空时直接发送此 Markdown 正文，不再重新生成日报",
    )


class WecomDailyReportTriggerOut(BaseModel):
    ok: bool
    platform: WecomDailyReportPlatform = "pdd"
    message: str = ""


class WecomInProgressDraftOut(BaseModel):
    draft: str = ""
    window_start: str = ""
    window_end: str = ""
    window_description: str = ""


class WecomDailyContentOut(BaseModel):
    content_date: str = ""
    pdd_in_progress: str = ""
    pdd_progress_summary: str = ""
    pdd_store_progress: str = ""
    pdd_listing_window_start: str = ""
    pdd_listing_window_end: str = ""
    pdd_git_window_start: str = ""
    pdd_git_window_end: str = ""
    pdd_preview_saved: bool = False
    taobao_netdisk_materials: str = ""
    taobao_in_progress: str = ""
    updated_at: str = ""
    database_available: bool = False


class WecomDailyContentUpdateIn(BaseModel):
    pdd_in_progress: str = ""
    taobao_netdisk_materials: str = ""
    taobao_in_progress: str = ""


class WecomDailyPreviewSaveIn(BaseModel):
    progress_summary: str = ""
    store_progress: str = ""
    in_progress: str = ""
    listing_window_start: str = ""
    listing_window_end: str = ""
    git_window_start: str = ""
    git_window_end: str = ""


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
    limited_time_success_count: int = 0
    activity_register_success_count: int = 0
    promotion_success_count: int = 0


class WecomDailyReportLogOut(BaseModel):
    log_id: str
    platform: WecomDailyReportPlatform
    report_date: str
    window_start: str = ""
    window_end: str = ""
    message_preview: str = ""
    trigger_kind: str = ""
    status: str = ""
    errcode: int = 0
    errmsg: str = ""
    webhook_target: str = ""
    created_at: str = ""


class WecomDailyReportLogListOut(BaseModel):
    items: list[WecomDailyReportLogOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class WecomDailyReportLogDetailOut(BaseModel):
    log_id: str
    platform: WecomDailyReportPlatform
    report_date: str
    window_start: str = ""
    window_end: str = ""
    message: str = ""
    trigger_kind: str = ""
    status: str = ""
    errcode: int = 0
    errmsg: str = ""
    webhook_target: str = ""
    created_at: str = ""


class WecomDailyReportPreviewOut(BaseModel):
    platform: WecomDailyReportPlatform = "pdd"
    report_date: str
    repo_path: str = ""
    commit_count: int = 0
    progress_summary: str = ""
    progress_summary_from_cache: bool = False
    store_progress: str = ""
    netdisk_materials: str = ""
    in_progress: str = ""
    in_progress_manual: str = ""
    in_progress_auto_draft: str = ""
    listing_window_start: str = ""
    listing_window_end: str = ""
    git_window_start: str = ""
    git_window_end: str = ""
    store_summaries: list[WecomDailyReportStoreOut] = Field(default_factory=list)
    message: str
    commits: list[WecomDailyReportCommitOut] = Field(default_factory=list)

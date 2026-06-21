"""投流昨日数据定时任务 API 模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TrafficReportScheduleOut(BaseModel):
    enabled: bool = True
    traffic_report_enabled: bool = True
    schedule_hour: int = 0
    schedule_minute: int = 1
    schedule_time: str = "00:01"
    timezone: str = "Asia/Shanghai"
    account_ids: list[str] = Field(default_factory=lambda: ["store_A"])
    table_name: str = "PDD营销日志表"
    scheduler_running: bool = False
    database_available: bool = False
    last_run_date: str = ""
    description: str = "每天抓取稳定成本推广昨日数据并写入飞书 PDD营销日志表"


class TrafficReportScheduleUpdateIn(BaseModel):
    traffic_report_enabled: bool | None = None
    schedule_hour: int | None = Field(default=None, ge=0, le=23)
    schedule_minute: int | None = Field(default=None, ge=0, le=59)
    account_ids: list[str] | None = None


class TrafficReportScheduleTriggerOut(BaseModel):
    enqueued: int = 0
    account_ids: list[str] = Field(default_factory=list)
    message: str = ""

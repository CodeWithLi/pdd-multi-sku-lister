"""投流昨日数据定时任务：查询配置、修改时间、手动触发。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.traffic_report_schedule import (
    TrafficReportScheduleOut,
    TrafficReportScheduleTriggerOut,
    TrafficReportScheduleUpdateIn,
)
from pdd_agent.api.services.traffic_report_scheduler import (
    TZ,
    get_traffic_report_scheduler,
)
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.session import is_database_available
from pdd_agent.integrations.feishu.config import (
    load_feishu_config,
    save_pdd_marketing_log_schedule_to_config,
)

router = APIRouter(prefix="/traffic-report-schedule", tags=["traffic-report-schedule"])


def _build_schedule_out() -> TrafficReportScheduleOut:
    cfg = load_feishu_config()
    marketing = cfg.pdd_marketing_log
    scheduler = get_traffic_report_scheduler()
    hour = int(marketing.traffic_report_schedule_hour)
    minute = int(marketing.traffic_report_schedule_minute)
    return TrafficReportScheduleOut(
        enabled=bool(marketing.enabled),
        traffic_report_enabled=bool(marketing.traffic_report_enabled),
        schedule_hour=hour,
        schedule_minute=minute,
        schedule_time=f"{hour:02d}:{minute:02d}",
        account_ids=list(marketing.traffic_report_account_ids or ["store_A"]),
        table_name=str(marketing.table_name or "PDD营销日志表"),
        scheduler_running=scheduler.is_running,
        database_available=is_database_available(),
        last_run_date=scheduler.last_run_date.isoformat() if scheduler.last_run_date else "",
    )


@router.get("", response_model=TrafficReportScheduleOut)
def get_traffic_report_schedule():
    """读取投流昨日数据定时任务配置与调度器状态。"""
    return _build_schedule_out()


@router.put("", response_model=TrafficReportScheduleOut)
def update_traffic_report_schedule(body: TrafficReportScheduleUpdateIn):
    """保存定时任务配置到 feishu.yaml（修改后下次调度周期生效）。"""
    save_pdd_marketing_log_schedule_to_config(
        traffic_report_enabled=body.traffic_report_enabled,
        traffic_report_schedule_hour=body.schedule_hour,
        traffic_report_schedule_minute=body.schedule_minute,
        traffic_report_account_ids=body.account_ids,
    )
    get_traffic_report_scheduler().reset_last_run_date()
    return _build_schedule_out()


@router.post("/trigger", response_model=TrafficReportScheduleTriggerOut)
def trigger_traffic_report_schedule():
    """立即手动触发一次投流昨日数据抓取（等同定时任务入队逻辑）。"""
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用，无法入队任务")

    cfg = load_feishu_config()
    marketing = cfg.pdd_marketing_log
    if not marketing.enabled:
        raise HTTPException(status_code=422, detail="PDD 营销日志表未启用")
    if not marketing.traffic_report_enabled:
        raise HTTPException(status_code=422, detail="投流昨日数据定时抓取未启用")

    settings = load_yaml_settings()
    allowed_ids = {
        str(aid).strip()
        for aid in (marketing.traffic_report_account_ids or ["store_A"])
        if str(aid).strip()
    }
    accounts = [
        acc.account_id
        for acc in settings.accounts
        if acc.enabled and acc.account_id in allowed_ids
    ]
    if not accounts:
        raise HTTPException(
            status_code=422,
            detail=f"未找到可触发的启用店铺：{sorted(allowed_ids)}",
        )

    count = get_traffic_report_scheduler().trigger_now()
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    return TrafficReportScheduleTriggerOut(
        enqueued=count,
        account_ids=accounts,
        message=f"已入队 {count} 家店铺投流昨日数据抓取，触发时间 {now}",
    )

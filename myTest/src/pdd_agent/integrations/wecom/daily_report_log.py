"""企业微信日报发送历史记录。"""

from __future__ import annotations

from datetime import date, datetime

from pdd_agent.db.repositories import insert_wecom_daily_report_log


def record_daily_report_send(
    *,
    platform: str,
    report_date: date,
    message: str,
    trigger_kind: str,
    ok: bool,
    errcode: int = 0,
    errmsg: str = "",
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    webhook_target: str = "daily_report",
) -> None:
    insert_wecom_daily_report_log(
        platform=platform,
        report_date=report_date,
        message=message,
        trigger_kind=trigger_kind,
        status="success" if ok else "failed",
        errcode=int(errcode or 0),
        errmsg=str(errmsg or ""),
        window_start=window_start,
        window_end=window_end,
        webhook_target=webhook_target,
    )

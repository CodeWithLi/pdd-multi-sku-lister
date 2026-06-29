"""失败日志循环上架每日统计 API。"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.daily_cycle_relists import (
    DailyCycleRelistRecordListResponse,
    DailyCycleRelistRecordOut,
    DailyCycleRelistShopSummary,
    DailyCycleRelistSummaryResponse,
)
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.db.repositories import (
    count_daily_cycle_relist_records,
    list_daily_cycle_relist_records,
    summarize_daily_cycle_relist_records,
)
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/daily-cycle-relists", tags=["daily-cycle-relists"])


def _parse_triggered_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        return datetime.now().date()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="triggered_date must be YYYY-MM-DD") from exc


def _row_out(row) -> DailyCycleRelistRecordOut:
    return DailyCycleRelistRecordOut(
        record_id=row.record_id,
        feishu_record_id=row.feishu_record_id or "",
        account_id=row.account_id,
        shop_display_name=row.shop_display_name or "",
        merchant_code=row.merchant_code or "",
        pipeline_id=row.pipeline_id,
        product_codes=list(row.product_codes or []),
        report_platform=row.report_platform or "",
        trigger_source=row.trigger_source or "auto_watch",
        triggered_at=row.triggered_at,
        created_at=row.created_at,
    )


@router.get("", response_model=DailyCycleRelistRecordListResponse)
def list_daily_cycle_relists(
    account_id: str = "",
    triggered_date: str = "",
    limit: int = 200,
):
    if not is_database_available():
        return DailyCycleRelistRecordListResponse(
            triggered_date=datetime.now().date(),
            total=0,
            items=[],
        )
    account_id = str(account_id or "").strip()
    if account_id and not get_account_or_none(account_id):
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")
    target = _parse_triggered_date(triggered_date)
    rows = list_daily_cycle_relist_records(
        account_id=account_id,
        triggered_date=target,
        limit=limit,
    )
    total = count_daily_cycle_relist_records(account_id=account_id, triggered_date=target)
    return DailyCycleRelistRecordListResponse(
        triggered_date=target,
        total=total,
        items=[_row_out(row) for row in rows],
    )


@router.get("/summary", response_model=DailyCycleRelistSummaryResponse)
def summarize_daily_cycle_relists(triggered_date: str = ""):
    target = _parse_triggered_date(triggered_date)
    if not is_database_available():
        return DailyCycleRelistSummaryResponse(triggered_date=target, total=0, by_shop=[])
    by_shop = summarize_daily_cycle_relist_records(triggered_date=target)
    total = count_daily_cycle_relist_records(triggered_date=target)
    return DailyCycleRelistSummaryResponse(
        triggered_date=target,
        total=total,
        by_shop=[DailyCycleRelistShopSummary(**item) for item in by_shop],
    )

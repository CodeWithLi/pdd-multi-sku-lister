"""整合链路上架跳过每日统计 API。"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.daily_pipeline_listing_skips import (
    DailyPipelineListingSkipRecordListResponse,
    DailyPipelineListingSkipRecordOut,
    DailyPipelineListingSkipShopSummary,
    DailyPipelineListingSkipSummaryResponse,
)
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.api.services.pipeline_listing_skip_record import (
    list_daily_pipeline_listing_skips,
    summarize_daily_pipeline_listing_skips,
)
from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/daily-pipeline-listing-skips", tags=["daily-pipeline-listing-skips"])


def _parse_skip_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        return datetime.now().date()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="skip_date must be YYYY-MM-DD") from exc


def _record_out(item: dict) -> DailyPipelineListingSkipRecordOut:
    account_id = str(item.get("account_id") or "").strip()
    return DailyPipelineListingSkipRecordOut(
        record_id=str(item.get("record_id") or ""),
        pipeline_id=str(item.get("pipeline_id") or ""),
        listing_run_id=str(item.get("listing_run_id") or ""),
        account_id=account_id,
        shop_display_name=resolve_account_display_name(account_id) if account_id else "",
        skip_kind=str(item.get("skip_kind") or ""),
        skip_kind_label=str(item.get("skip_kind_label") or ""),
        product_selector=str(item.get("product_selector") or ""),
        merchant_code=str(item.get("merchant_code") or ""),
        listing_label=str(item.get("listing_label") or ""),
        message=str(item.get("message") or ""),
        created_at=item.get("created_at"),
    )


@router.get("", response_model=DailyPipelineListingSkipRecordListResponse)
def list_daily_pipeline_listing_skip_records(
    skip_date: str = "",
    account_id: str = "",
    skip_kind: str = "",
    limit: int = 200,
):
    target = _parse_skip_date(skip_date)
    if not is_database_available():
        return DailyPipelineListingSkipRecordListResponse(skip_date=target)
    account_id = str(account_id or "").strip()
    if account_id and not get_account_or_none(account_id):
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")
    summary = summarize_daily_pipeline_listing_skips(skip_date=target, account_id=account_id)
    rows = list_daily_pipeline_listing_skips(
        skip_date=target,
        account_id=account_id,
        skip_kind=skip_kind,
        limit=limit,
    )
    return DailyPipelineListingSkipRecordListResponse(
        skip_date=target,
        total=int(summary.get("total") or 0),
        platform_skip_dedupe=int(summary.get("platform_skip_dedupe") or 0),
        bag_view_missing=int(summary.get("bag_view_missing") or 0),
        items=[_record_out(item) for item in rows],
    )


@router.get("/summary", response_model=DailyPipelineListingSkipSummaryResponse)
def summarize_daily_pipeline_listing_skip_records(
    skip_date: str = "",
    account_id: str = "",
):
    target = _parse_skip_date(skip_date)
    if not is_database_available():
        return DailyPipelineListingSkipSummaryResponse(skip_date=target)
    account_id = str(account_id or "").strip()
    if account_id and not get_account_or_none(account_id):
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")
    summary = summarize_daily_pipeline_listing_skips(skip_date=target, account_id=account_id)
    return DailyPipelineListingSkipSummaryResponse(
        skip_date=target,
        total=int(summary.get("total") or 0),
        platform_skip_dedupe=int(summary.get("platform_skip_dedupe") or 0),
        bag_view_missing=int(summary.get("bag_view_missing") or 0),
        pipeline_count=int(summary.get("pipeline_count") or 0),
        by_shop=[
            DailyPipelineListingSkipShopSummary(**item)
            for item in (summary.get("by_shop") or [])
        ],
    )

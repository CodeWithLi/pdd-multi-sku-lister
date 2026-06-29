"""每日上架成功记录 API。"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.daily_listings import (
    DailyListingRecordListResponse,
    DailyListingRecordOut,
    DailyListingShopSummary,
    DailyListingSummaryResponse,
)
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.db.repositories import (
    count_daily_listing_records,
    list_daily_listing_records,
    summarize_daily_listing_records,
)
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/daily-listings", tags=["daily-listings"])


def _parse_listed_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        return datetime.now().date()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="listed_date must be YYYY-MM-DD") from exc


def _row_out(row) -> DailyListingRecordOut:
    return DailyListingRecordOut(
        record_id=row.record_id,
        account_id=row.account_id,
        shop_display_name=row.shop_display_name or "",
        pdd_product_id=row.pdd_product_id,
        product_code=row.product_code,
        family_code=row.family_code or "",
        image_set=row.image_set or "",
        listing_label=row.listing_label or "",
        merchant_code=row.merchant_code or "",
        title=row.title or "",
        source_run_id=row.source_run_id or "",
        source_kind=row.source_kind or "listing",
        pipeline_id=row.pipeline_id or "",
        listed_at=row.listed_at,
        created_at=row.created_at,
    )


@router.get("", response_model=DailyListingRecordListResponse)
def list_daily_listings(
    account_id: str = "",
    listed_date: str = "",
    limit: int = 200,
):
    if not is_database_available():
        return DailyListingRecordListResponse(
            listed_date=datetime.now().date(),
            total=0,
            items=[],
        )
    account_id = str(account_id or "").strip()
    if account_id and not get_account_or_none(account_id):
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")
    target = _parse_listed_date(listed_date)
    rows = list_daily_listing_records(
        account_id=account_id,
        listed_date=target,
        limit=limit,
    )
    total = count_daily_listing_records(account_id=account_id, listed_date=target)
    return DailyListingRecordListResponse(
        listed_date=target,
        total=total,
        items=[_row_out(row) for row in rows],
    )


@router.get("/summary", response_model=DailyListingSummaryResponse)
def summarize_daily_listings(listed_date: str = ""):
    target = _parse_listed_date(listed_date)
    if not is_database_available():
        return DailyListingSummaryResponse(listed_date=target, total=0, by_shop=[])
    by_shop = summarize_daily_listing_records(listed_date=target)
    total = count_daily_listing_records(listed_date=target)
    return DailyListingSummaryResponse(
        listed_date=target,
        total=total,
        by_shop=[DailyListingShopSummary(**item) for item in by_shop],
    )

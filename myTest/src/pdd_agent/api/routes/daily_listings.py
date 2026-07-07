"""每日上架成功记录 API。"""



from __future__ import annotations



from datetime import date, datetime

from typing import Literal



from fastapi import APIRouter, HTTPException



from pdd_agent.api.schemas.daily_listings import (

    DailyListingRecordListResponse,

    DailyListingRecordOut,

    DailyListingShopSummary,

    DailyListingSummaryResponse,

)

from pdd_agent.api.services.config_service import get_account_or_none

from pdd_agent.api.services.daily_shop_publish_stats import (

    count_limited_time_success_total,
    count_activity_register_success_total,
    count_promotion_success_total,

    enrich_listing_shop_summaries,

    enrich_listing_shop_summaries_between,

    summarize_shop_publish_stats_for_calendar_day,

    summarize_shop_publish_stats_for_report_day,

)

from pdd_agent.core.report_time_window import (

    CALENDAR_WINDOW_DESCRIPTION,

    REPORT_WINDOW_DESCRIPTION,

    format_report_window_iso,

    report_listing_window,

)

from pdd_agent.db.repositories import (

    count_daily_listing_records,

    count_daily_listing_records_between,

    list_daily_listing_records,

    list_daily_listing_records_between,

    summarize_daily_listing_records,

    summarize_daily_listing_records_between,

)

from pdd_agent.db.session import is_database_available



router = APIRouter(prefix="/daily-listings", tags=["daily-listings"])



DailyListingWindowMode = Literal["calendar", "report"]





def _parse_listed_date(value: str) -> date:

    text = str(value or "").strip()

    if not text:

        return datetime.now().date()

    try:

        return date.fromisoformat(text)

    except ValueError as exc:

        raise HTTPException(status_code=422, detail="listed_date must be YYYY-MM-DD") from exc





def _parse_window_mode(value: str) -> DailyListingWindowMode:

    mode = str(value or "calendar").strip().lower()

    if mode not in ("calendar", "report"):

        raise HTTPException(status_code=422, detail="window_mode must be calendar or report")

    return mode  # type: ignore[return-value]





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

        status=str(row.status or "active"),

        listed_at=row.listed_at,

        delisted_at=row.delisted_at,

        created_at=row.created_at,

    )





@router.get("", response_model=DailyListingRecordListResponse)

def list_daily_listings(

    account_id: str = "",

    listed_date: str = "",

    window_mode: str = "calendar",

    limit: int = 200,

    active_only: bool = False,

):

    target = _parse_listed_date(listed_date)

    mode = _parse_window_mode(window_mode)

    if not is_database_available():

        return DailyListingRecordListResponse(

            listed_date=target,

            window_mode=mode,

            total=0,

            active_total=0,

            delisted_total=0,

            items=[],

        )

    account_id = str(account_id or "").strip()

    if account_id and not get_account_or_none(account_id):

        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")



    if mode == "report":

        start, end = report_listing_window(reference_day=target)

        window_start, window_end = format_report_window_iso(start, end)

        rows = list_daily_listing_records_between(

            account_id=account_id,

            start=start,

            end=end,

            inclusive_end=True,

            limit=limit,

            active_only=active_only,

        )

        total = count_daily_listing_records_between(

            account_id=account_id,

            start=start,

            end=end,

            inclusive_end=True,

        )

        active_total = count_daily_listing_records_between(

            account_id=account_id,

            start=start,

            end=end,

            inclusive_end=True,

            active_only=True,

        )

        return DailyListingRecordListResponse(

            listed_date=target,

            window_mode=mode,

            window_start=window_start,

            window_end=window_end,

            window_description=REPORT_WINDOW_DESCRIPTION,

            total=total,

            active_total=active_total,

            delisted_total=max(0, total - active_total),

            items=[_row_out(row) for row in rows],

        )



    rows = list_daily_listing_records(

        account_id=account_id,

        listed_date=target,

        limit=limit,

        active_only=active_only,

    )

    total = count_daily_listing_records(account_id=account_id, listed_date=target)

    active_total = count_daily_listing_records(

        account_id=account_id,

        listed_date=target,

        active_only=True,

    )

    return DailyListingRecordListResponse(

        listed_date=target,

        window_mode=mode,

        window_description=CALENDAR_WINDOW_DESCRIPTION,

        total=total,

        active_total=active_total,

        delisted_total=max(0, total - active_total),

        items=[_row_out(row) for row in rows],

    )





@router.get("/summary", response_model=DailyListingSummaryResponse)

def summarize_daily_listings(listed_date: str = "", window_mode: str = "calendar"):

    target = _parse_listed_date(listed_date)

    mode = _parse_window_mode(window_mode)

    if not is_database_available():

        return DailyListingSummaryResponse(

            listed_date=target,

            window_mode=mode,

            total=0,

            active_total=0,

            delisted_total=0,

            limited_time_success_total=0,

            activity_register_success_total=0,

            promotion_success_total=0,

            by_shop=[],

        )



    if mode == "report":

        start, end = report_listing_window(reference_day=target)

        window_start, window_end = format_report_window_iso(start, end)

        by_shop = summarize_daily_listing_records_between(start=start, end=end)

        by_shop = enrich_listing_shop_summaries_between(

            by_shop,

            start=start,

            end=end,

            inclusive_end=True,

        )

        stats = summarize_shop_publish_stats_for_report_day(reference_day=target)

        total = count_daily_listing_records_between(

            start=start,

            end=end,

            inclusive_end=True,

        )

        active_total = count_daily_listing_records_between(

            start=start,

            end=end,

            inclusive_end=True,

            active_only=True,

        )

        return DailyListingSummaryResponse(

            listed_date=target,

            window_mode=mode,

            window_start=window_start,

            window_end=window_end,

            window_description=REPORT_WINDOW_DESCRIPTION,

            total=total,

            active_total=active_total,

            delisted_total=max(0, total - active_total),

            limited_time_success_total=count_limited_time_success_total(stats),

            activity_register_success_total=count_activity_register_success_total(stats),

            promotion_success_total=count_promotion_success_total(stats),

            by_shop=[DailyListingShopSummary(**item) for item in by_shop],

        )



    by_shop = summarize_daily_listing_records(listed_date=target)

    by_shop = enrich_listing_shop_summaries(by_shop, listed_date=target)

    stats = summarize_shop_publish_stats_for_calendar_day(target)

    total = count_daily_listing_records(listed_date=target)

    active_total = count_daily_listing_records(listed_date=target, active_only=True)

    return DailyListingSummaryResponse(

        listed_date=target,

        window_mode=mode,

        window_description=CALENDAR_WINDOW_DESCRIPTION,

        total=total,

        active_total=active_total,

        delisted_total=max(0, total - active_total),

        limited_time_success_total=count_limited_time_success_total(stats),

        activity_register_success_total=count_activity_register_success_total(stats),

        promotion_success_total=count_promotion_success_total(stats),

        by_shop=[DailyListingShopSummary(**item) for item in by_shop],

    )


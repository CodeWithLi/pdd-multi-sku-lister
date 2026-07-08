"""负库存下架/恢复上架每日统计 API。"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.daily_inventory_delist import (
    DailyInventoryDelistRecordListResponse,
    DailyInventoryDelistRecordOut,
    DailyInventoryDelistShopSummary,
    DailyInventoryDelistSummaryResponse,
)
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.db.repositories import (
    count_daily_inventory_delist_records,
    count_daily_inventory_relist_records,
    list_daily_inventory_delist_records,
    list_daily_inventory_relist_records,
    summarize_daily_inventory_delist_records,
    summarize_daily_inventory_relist_records,
)
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/daily-inventory-delist", tags=["daily-inventory-delist"])


def _parse_stat_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        return datetime.now().date()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="stat_date must be YYYY-MM-DD") from exc


def _row_out(row) -> DailyInventoryDelistRecordOut:
    return DailyInventoryDelistRecordOut(
        record_id=row.record_id,
        account_id=row.account_id,
        shop_display_name=row.shop_display_name or "",
        product_code=row.product_code,
        merchant_code=row.merchant_code or "",
        pdd_product_id=row.pdd_product_id or "",
        erp_available_qty=row.erp_available_qty,
        delist_status=row.delist_status or "",
        message=row.message or "",
        is_relisted=bool(row.is_relisted),
        delisted_at=row.delisted_at,
        relisted_at=row.relisted_at,
        trigger=row.trigger or "",
    )


@router.get("/summary", response_model=DailyInventoryDelistSummaryResponse)
def summarize_daily_inventory_delist(stat_date: str = ""):
    target = _parse_stat_date(stat_date)
    if not is_database_available():
        return DailyInventoryDelistSummaryResponse(stat_date=target)
    delist_by_shop = summarize_daily_inventory_delist_records(stat_date=target)
    relist_by_shop = summarize_daily_inventory_relist_records(stat_date=target)
    return DailyInventoryDelistSummaryResponse(
        stat_date=target,
        delist_total=count_daily_inventory_delist_records(stat_date=target),
        relist_total=count_daily_inventory_relist_records(stat_date=target),
        delist_by_shop=[DailyInventoryDelistShopSummary(**item) for item in delist_by_shop],
        relist_by_shop=[DailyInventoryDelistShopSummary(**item) for item in relist_by_shop],
    )


@router.get("", response_model=DailyInventoryDelistRecordListResponse)
def list_daily_inventory_delist_items(
    stat_date: str = "",
    action: str = Query(default="delist", pattern="^(delist|relist)$"),
    account_id: str = "",
    limit: int = 200,
):
    target = _parse_stat_date(stat_date)
    if not is_database_available():
        return DailyInventoryDelistRecordListResponse(stat_date=target, action=action)
    account_id = str(account_id or "").strip()
    if account_id and not get_account_or_none(account_id):
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")

    if action == "relist":
        rows = list_daily_inventory_relist_records(
            stat_date=target,
            account_id=account_id,
            limit=limit,
        )
        total = count_daily_inventory_relist_records(stat_date=target, account_id=account_id)
    else:
        rows = list_daily_inventory_delist_records(
            stat_date=target,
            account_id=account_id,
            limit=limit,
        )
        total = count_daily_inventory_delist_records(stat_date=target, account_id=account_id)

    return DailyInventoryDelistRecordListResponse(
        stat_date=target,
        action=action,
        total=total,
        items=[_row_out(row) for row in rows],
    )

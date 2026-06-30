"""每日上架记录 API 模型。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyListingRecordOut(BaseModel):
    record_id: str
    account_id: str
    shop_display_name: str = ""
    pdd_product_id: str
    product_code: str
    family_code: str = ""
    image_set: str = ""
    listing_label: str = ""
    merchant_code: str = ""
    title: str = ""
    source_run_id: str = ""
    source_kind: str = "listing"
    pipeline_id: str = ""
    status: str = "active"
    listed_at: datetime
    delisted_at: datetime | None = None
    created_at: datetime | None = None


class DailyListingRecordListResponse(BaseModel):
    listed_date: date
    total: int = 0
    active_total: int = 0
    delisted_total: int = 0
    items: list[DailyListingRecordOut] = Field(default_factory=list)


class DailyListingShopSummary(BaseModel):
    account_id: str
    shop_display_name: str = ""
    count: int = 0
    active_count: int = 0
    delisted_count: int = 0


class DailyListingSummaryResponse(BaseModel):
    listed_date: date
    total: int = 0
    active_total: int = 0
    delisted_total: int = 0
    by_shop: list[DailyListingShopSummary] = Field(default_factory=list)

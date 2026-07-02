"""整合链路上架跳过每日统计 API 模型。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyPipelineListingSkipRecordOut(BaseModel):
    record_id: str
    pipeline_id: str
    listing_run_id: str = ""
    account_id: str = ""
    shop_display_name: str = ""
    skip_kind: str
    skip_kind_label: str = ""
    product_selector: str = ""
    merchant_code: str = ""
    listing_label: str = ""
    message: str = ""
    created_at: datetime


class DailyPipelineListingSkipRecordListResponse(BaseModel):
    skip_date: date
    total: int = 0
    platform_skip_dedupe: int = 0
    bag_view_missing: int = 0
    items: list[DailyPipelineListingSkipRecordOut] = Field(default_factory=list)


class DailyPipelineListingSkipShopSummary(BaseModel):
    account_id: str
    shop_display_name: str = ""
    total: int = 0
    platform_skip_dedupe: int = 0
    bag_view_missing: int = 0


class DailyPipelineListingSkipSummaryResponse(BaseModel):
    skip_date: date
    total: int = 0
    platform_skip_dedupe: int = 0
    bag_view_missing: int = 0
    pipeline_count: int = 0
    by_shop: list[DailyPipelineListingSkipShopSummary] = Field(default_factory=list)

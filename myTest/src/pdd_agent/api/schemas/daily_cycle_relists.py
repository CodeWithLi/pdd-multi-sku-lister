"""失败日志循环上架每日统计 API 模型。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyCycleRelistRecordOut(BaseModel):
    record_id: str
    feishu_record_id: str = ""
    account_id: str
    shop_display_name: str = ""
    merchant_code: str = ""
    pipeline_id: str
    product_codes: list[str] = Field(default_factory=list)
    report_platform: str = ""
    trigger_source: str = "auto_watch"
    triggered_at: datetime
    created_at: datetime | None = None


class DailyCycleRelistRecordListResponse(BaseModel):
    triggered_date: date
    total: int = 0
    items: list[DailyCycleRelistRecordOut] = Field(default_factory=list)


class DailyCycleRelistShopSummary(BaseModel):
    account_id: str
    shop_display_name: str = ""
    count: int = 0


class DailyCycleRelistSummaryResponse(BaseModel):
    triggered_date: date
    total: int = 0
    by_shop: list[DailyCycleRelistShopSummary] = Field(default_factory=list)

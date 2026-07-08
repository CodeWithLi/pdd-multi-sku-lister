"""负库存下架/恢复上架每日统计 API 模型。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyInventoryDelistShopSummary(BaseModel):
    account_id: str
    shop_display_name: str = ""
    count: int = 0


class DailyInventoryDelistRecordOut(BaseModel):
    record_id: str
    account_id: str
    shop_display_name: str = ""
    product_code: str
    merchant_code: str = ""
    pdd_product_id: str = ""
    erp_available_qty: int | None = None
    delist_status: str = ""
    message: str = ""
    is_relisted: bool = False
    delisted_at: datetime | None = None
    relisted_at: datetime | None = None
    trigger: str = ""


class DailyInventoryDelistSummaryResponse(BaseModel):
    stat_date: date
    delist_total: int = 0
    relist_total: int = 0
    delist_by_shop: list[DailyInventoryDelistShopSummary] = Field(default_factory=list)
    relist_by_shop: list[DailyInventoryDelistShopSummary] = Field(default_factory=list)


class DailyInventoryDelistRecordListResponse(BaseModel):
    stat_date: date
    action: str
    total: int = 0
    items: list[DailyInventoryDelistRecordOut] = Field(default_factory=list)

"""Published products API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from pdd_agent.api.schemas.catalog import ListingUnitOut


class PublishedProductOut(BaseModel):
    mapping_id: str
    account_id: str
    source_run_id: str = ""
    product_code: str
    image_set: str = ""
    listing_label: str
    merchant_code: str = ""
    pdd_product_id: str
    status: str = ""
    published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PublishedProductListResponse(BaseModel):
    items: list[PublishedProductOut] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class PublishedProductDetailResponse(BaseModel):
    published: PublishedProductOut
    run_result_item: dict[str, Any] = Field(default_factory=dict)
    source_run_result: dict[str, Any] = Field(default_factory=dict)
    unit_detail: ListingUnitOut | None = None

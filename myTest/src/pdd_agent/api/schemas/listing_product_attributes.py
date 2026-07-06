"""Listing product attribute API schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class ListingProductAttributeOut(BaseModel):
    field_key: str
    label: str
    selected_value: str = ""
    options: list[str] = Field(default_factory=list)
    enabled: bool = True
    sort_order: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ListingProductAttributeListResponse(BaseModel):
    items: list[ListingProductAttributeOut] = Field(default_factory=list)


class ListingProductAttributeUpdateIn(BaseModel):
    selected_value: str


class ListingProductAttributeBatchUpdateIn(BaseModel):
    attributes: dict[str, str] = Field(default_factory=dict)

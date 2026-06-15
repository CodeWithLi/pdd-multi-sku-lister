"""Failure workbench API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FailureItemOut(BaseModel):
    item_id: str
    source_run_id: str
    account_id: str
    listing_label: str
    product_code: str
    image_set: str = ""
    merchant_code: str = ""
    item_status: str
    reason: str = ""
    error: str = ""
    retryable: bool = False
    decision_status: str = "open"
    decision_note: str = ""
    retry_run_id: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FailureListResponse(BaseModel):
    items: list[FailureItemOut] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    summary: dict[str, int] = Field(default_factory=dict)


class FailureMarkRequest(BaseModel):
    decision_status: str = Field(..., pattern="^(open|handled|ignored|retrying)$")
    decision_note: str = ""


class FailureBulkMarkRequest(BaseModel):
    item_ids: list[str] = Field(..., min_length=1)
    decision_status: str = Field(..., pattern="^(open|handled|ignored|retrying)$")
    decision_note: str = ""


class FailureRetryRequest(BaseModel):
    item_ids: list[str] = Field(..., min_length=1)
    category_keyword: str = ""


class FailureRetryResult(BaseModel):
    item_id: str
    run_id: str = ""
    status: str
    message: str = ""


class FailureRetryResponse(BaseModel):
    total: int
    results: list[FailureRetryResult] = Field(default_factory=list)


class FailureSyncResponse(BaseModel):
    scanned_runs: int
    upserted_items: int


class FailureRawItem(BaseModel):
    source_run_id: str
    account_id: str
    item: dict[str, Any]


class ListingFailureDetailOut(BaseModel):
    detail_id: str
    failure_item_id: str = ""
    source_run_id: str = ""
    account_id: str = ""
    listing_label: str = ""
    product_code: str = ""
    image_set: str = ""
    family_code: str = ""
    merchant_code: str = ""
    phase: str = ""
    step: str = ""
    severity: str = "error"
    reason_code: str = ""
    message: str = ""
    error: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    screenshot_path: str = ""
    page_url: str = ""
    created_at: datetime | None = None


class ListingFailureDetailListResponse(BaseModel):
    items: list[ListingFailureDetailOut] = Field(default_factory=list)
    total: int = 0

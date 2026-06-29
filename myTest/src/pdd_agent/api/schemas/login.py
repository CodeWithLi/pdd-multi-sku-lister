"""Login health API schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class LoginStatusOut(BaseModel):
    account_id: str
    status: str = "unknown"
    reason: str = ""
    current_url: str = ""
    shop_display_name: str = ""
    checked_at: datetime | None = None


class LoginBatchCheckRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)
    delay_min_seconds: int | None = Field(default=None, ge=0, le=3600)
    delay_max_seconds: int | None = Field(default=None, ge=0, le=3600)


class LoginBatchCheckResponse(BaseModel):
    status: str = "running"
    total: int
    delay_min_seconds: int
    delay_max_seconds: int
    message: str = ""


class ShopNameScrapeBatchRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)
    delay_min_seconds: int | None = Field(default=None, ge=0, le=3600)
    delay_max_seconds: int | None = Field(default=None, ge=0, le=3600)


class ShopNameScrapeBatchResponse(BaseModel):
    status: str = "running"
    total: int
    delay_min_seconds: int
    delay_max_seconds: int
    message: str = ""


class ShopNameScrapeResultOut(BaseModel):
    account_id: str
    shop_display_name: str = ""
    ok: bool = False
    reason: str = ""


class OpenLoginWindowRequest(BaseModel):
    keep_open_seconds: int = Field(default=300, ge=30, le=1800)

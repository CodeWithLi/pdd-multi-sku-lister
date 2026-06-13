"""Style color cache API schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class StyleColorOut(BaseModel):
    product_code: str
    color_label: str
    source: str = "ai"
    image_path: str = ""
    image_mtime: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StyleColorListResponse(BaseModel):
    items: list[StyleColorOut] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class StyleColorCreateIn(BaseModel):
    product_code: str
    color_label: str
    image_path: str = ""


class StyleColorUpdateIn(BaseModel):
    color_label: str
    image_path: str | None = None

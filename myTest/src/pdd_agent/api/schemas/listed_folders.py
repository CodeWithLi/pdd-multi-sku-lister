"""已上架素材文件夹 API 模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ListedAssetFolderOut(BaseModel):
    record_id: str
    account_id: str
    folder_selector: str
    family_code: str = ""
    image_set: str = ""
    product_code: str = ""
    listing_label: str = ""
    asset_path: str = ""
    source_run_id: str = ""
    source_kind: str = "listing"
    pipeline_id: str = ""
    pdd_product_id: str = ""
    listed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ListedAssetFolderListResponse(BaseModel):
    items: list[ListedAssetFolderOut] = Field(default_factory=list)
    total: int = 0

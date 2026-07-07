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
    family_code: str = ""
    image_set: str = ""
    listing_label: str
    merchant_code: str = ""
    pdd_product_id: str
    status: str = ""
    published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    spec_metadata: dict[str, Any] = Field(default_factory=dict)
    price_sync_status: str = Field(
        default="none",
        description="none=未反查, specs_synced=拼多多规格价, local_skus=本地规格价, list_price=列表价, detail_opened=已打开详情, searched=已搜索",
    )
    price_sync_at: datetime | None = None
    limited_time_status: str = Field(
        default="",
        description="限时限量购报名状态：空=未报名, success=成功, failed=失败",
    )
    limited_time_error: str = Field(default="", description="限时限量购失败原因")
    limited_time_run_id: str = Field(default="", description="最近一次限时限量购 run_id")
    limited_time_completed_at: datetime | None = None


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


class PublishedProductDelistResponse(BaseModel):
    run_id: str
    status: str
    message: str = ""


class PublishedProductLookupResponse(BaseModel):
    run_id: str
    status: str
    message: str = ""


class PublishedProductDeleteResponse(BaseModel):
    ok: bool = True
    mapping_id: str
    message: str = ""


class PublishedProductManualCreateIn(BaseModel):
    """手动录入拼多多已有商品。"""

    account_id: str = Field(..., description="店铺 ID，与店铺设置、浏览器 Profile 一致，如 store_A")
    pdd_product_id: str = Field(..., description="拼多多商家后台的商品数字 ID")
    product_code: str = Field(..., description="商品编码，用于匹配「拼多多定价.xls / 控价.xls」，如 BD716A")
    listing_label: str = Field(..., description="在本系统列表中的显示名称，如 BD716A / 第一套图")
    family_code: str = Field(default="", description="母文件编码（可选），如 BD716；参与定价表模糊匹配")
    image_set: str = Field(default="", description="套图文件夹名（可选），如 第一套图；多套图商品必填")
    merchant_code: str = Field(default="", description="拼多多货号（可选），通常与款式编码相同，如 BD716A")
    status: str = Field(default="on_sale", description="on_sale=在售，delisted=已下架")
    note: str = Field(default="", description="备注，仅保存在 spec_metadata，方便日后识别来源")
    import_catalog_skus: bool = Field(
        default=True,
        description="是否从本地素材目录导入 SKU 规格（建议开启，活动价格校验需要）",
    )


class PublishedProductCreateResponse(BaseModel):
    published: PublishedProductOut
    catalog_hints: list[str] = Field(default_factory=list)
    message: str = ""

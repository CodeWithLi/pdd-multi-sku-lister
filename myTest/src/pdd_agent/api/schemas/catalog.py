"""素材目录 / 校验相关 API 模型。"""

from pydantic import BaseModel, Field


class SkuComboOut(BaseModel):
    style_code: str
    style_name: str
    model_code: str
    model_name: str
    combo_folder: str
    preview_image: str
    inventory: str
    group_price: str
    single_price: str


class ListingUnitOut(BaseModel):
    product_code: str
    family_code: str = ""
    image_set: str = ""
    listing_label: str
    merchant_code: str
    root: str
    carousel_images: list[str] = Field(default_factory=list)
    detail_images: list[str] = Field(default_factory=list)
    carousel_count: int
    detail_count: int
    sku_count: int
    style_codes: list[str] = Field(default_factory=list)
    model_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    skus: list[SkuComboOut] = Field(default_factory=list)


class ProductSummaryOut(BaseModel):
    product_code: str
    image_sets: list[str] = Field(default_factory=list)
    listing_unit_count: int


class ListingTargetOptionOut(BaseModel):
    selector: str
    family_code: str = ""
    image_set: str = ""
    product_codes: list[str] = Field(default_factory=list)
    product_count: int = 0
    listed_product_codes: list[str] = Field(default_factory=list)
    unlisted_product_codes: list[str] = Field(default_factory=list)
    listed_count: int = 0
    unlisted_count: int = 0
    is_fully_listed: bool = False
    has_pending_listing: bool = False
    is_material_ready: bool = True


class ProductDetailOut(BaseModel):
    product_code: str
    image_sets: list[str] = Field(default_factory=list)
    units: list[ListingUnitOut] = Field(default_factory=list)


class PreflightRequest(BaseModel):
    product_codes: list[str] = Field(..., min_length=1)


class PreflightIssueOut(BaseModel):
    level: str
    message: str
    listing_label: str = ""


class PreflightResponse(BaseModel):
    ok: bool
    unit_count: int
    error_count: int
    warning_count: int
    units: list[ListingUnitOut] = Field(default_factory=list)
    issues: list[PreflightIssueOut] = Field(default_factory=list)

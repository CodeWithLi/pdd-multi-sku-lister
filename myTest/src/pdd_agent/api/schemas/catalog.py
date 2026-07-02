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
    material_image: str = ""
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
    material_source: str = Field(default="local", description="local | minio")


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


class MinioRabbitMQQueueUpdate(BaseModel):
    queue: str = Field(..., min_length=1)


class MinioTestUploadRequest(BaseModel):
    family_code: str = Field(default="BD999", min_length=1)
    image_set: str = Field(default="第一套图", min_length=1)
    product_code: str = Field(default="BD999A测试笔袋", min_length=1)
    category: str = Field(default="", description="留空则用 minio.yaml categories 第一项")
    image_numbers: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])
    upload_method: str = Field(
        default="alist",
        description="alist=经 Alist 上传（生产路径）；minio=API 直传（仅调试）",
    )
    publish_rabbitmq: bool = Field(
        default=False,
        description="仅 upload_method=minio 时有效：手动模拟 MQ 通知",
    )
    process_local: bool = Field(
        default=False,
        description="仅 upload_method=minio 且 publish_rabbitmq=true 时：本进程立即处理",
    )


class MinioSyncStartRequest(BaseModel):
    product_codes: list[str] = Field(..., min_length=1)


class MinioSyncJobOut(BaseModel):
    job_id: str
    status: str
    product_codes: list[str] = Field(default_factory=list)
    total_sets: int = 0
    completed_sets: int = 0
    current_label: str = ""
    downloaded_files: int = 0
    skipped_files: int = 0
    pruned_dirs: int = 0
    pruned_files: int = 0
    pruned_sets: int = 0
    error: str = ""
    progress_percent: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0


class MinioRefreshModeUpdate(BaseModel):
    refresh_mode: str = Field(..., description="poll | rabbitmq")


class MinioImageSetDeleteRequest(BaseModel):
    selector: str = Field(default="", description="套图选择器，如 BD021/第一套图")
    family_code: str = Field(default="")
    image_set: str = Field(default="")
    sync_alist: bool = Field(default=True, description="同时删除 Alist 对应目录")
    clear_local_cache: bool = Field(default=True, description="同时清理本地 MinIO 缓存")


class MinioImageSetDeleteResponse(BaseModel):
    selector: str
    family_code: str
    image_set: str
    object_prefix: str
    deleted_object_count: int
    alist_deleted: bool
    alist_virtual_path: str
    local_cache_cleared: bool
    index_removed: bool
    cleaned_family_objects: int = 0
    family_folder_removed: bool = False
    remaining_object_count: int = 0
    summary: str


class MinioProductDeleteRequest(BaseModel):
    selector: str = Field(default="", description="商品选择器，如 BD713/第一套图/BD713B")
    family_code: str = Field(default="")
    image_set: str = Field(default="")
    product_code: str = Field(default="")
    sync_alist: bool = Field(default=True, description="同时删除 Alist 对应目录")
    clear_local_cache: bool = Field(default=True, description="同时清理本地 MinIO 缓存")


class MinioProductDeleteResponse(BaseModel):
    selector: str
    family_code: str
    image_set: str
    product_code: str
    object_prefix: str
    deleted_object_count: int
    alist_deleted: bool
    alist_virtual_path: str
    local_cache_cleared: bool
    index_updated: bool
    image_set_removed: bool = False
    family_folder_removed: bool = False
    cleaned_set_objects: int = 0
    cleaned_family_objects: int = 0
    remaining_object_count: int = 0
    summary: str

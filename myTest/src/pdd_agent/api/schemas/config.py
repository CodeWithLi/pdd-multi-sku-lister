"""配置相关 API 模型。"""

import re

from pydantic import BaseModel, Field, field_validator, model_validator

_ACCOUNT_ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


class AccountOut(BaseModel):
    """列表展示（不含密码明文）。"""

    account_id: str
    enabled: bool
    username: str = ""
    has_password: bool = False
    product_codes: list[str] = Field(default_factory=list)


class AccountDetailOut(AccountOut):
    """编辑用详情（本地控制台，含密码）。"""

    password: str = ""


class AccountCreateIn(BaseModel):
    account_id: str = Field(..., min_length=1, max_length=64)
    enabled: bool = True
    username: str = ""
    password: str = ""
    product_codes: list[str] = Field(default_factory=list)

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, v: str) -> str:
        v = v.strip()
        if not _ACCOUNT_ID_PATTERN.match(v):
            raise ValueError("店铺 ID 须以字母开头，仅含字母、数字、下划线")
        return v


class AccountUpdateIn(BaseModel):
    enabled: bool = True
    username: str = ""
    password: str = ""  # 留空表示不修改密码
    product_codes: list[str] = Field(default_factory=list)


class ConfigSummaryOut(BaseModel):
    """系统配置摘要。"""

    app_name: str
    log_level: str
    assets_root: str
    excel_path: str
    llm_configured: bool
    database_configured: bool = False
    database_available: bool = False
    database_error: str = ""
    account_count: int
    enabled_account_count: int


class AppConfigIn(BaseModel):
    name: str = "pdd-agent-platform"
    log_level: str = "INFO"


class PathsConfigIn(BaseModel):
    assets_root: str = "data/assets"
    profiles_root: str = "data/profiles"
    runs_root: str = "data/runs"


class BrowserConfigIn(BaseModel):
    headless: bool = False
    slow_mo: int = 0
    default_timeout_ms: int = 30_000
    base_url: str = "https://mms.pinduoduo.com"
    channel: str = ""


class MultiSpecConfigIn(BaseModel):
    excel: str = "data/assets/sku+名称.xlsx"
    defaults: dict[str, str] = Field(default_factory=dict)


class ListingConfigIn(BaseModel):
    category_keyword: str = "玩偶"
    title_mode: str = "page_ai"


class DelistConfigIn(BaseModel):
    min_created_after: str = ""
    dry_run: bool = True
    merchant_code_contains: str = ""
    max_delist_per_run: int = 50
    account_ids: list[str] = Field(default_factory=list)


class BatchConfigIn(BaseModel):
    max_concurrent_stores: int = Field(default=3, ge=1, le=5)
    store_start_delay_min_seconds: int = Field(default=30, ge=0, le=3600)
    store_start_delay_max_seconds: int = Field(default=180, ge=0, le=3600)

    @model_validator(mode="after")
    def validate_delay_range(self) -> "BatchConfigIn":
        if self.store_start_delay_max_seconds < self.store_start_delay_min_seconds:
            self.store_start_delay_max_seconds = self.store_start_delay_min_seconds
        return self


class RuntimeConfigOut(BaseModel):
    app: AppConfigIn
    paths: PathsConfigIn
    browser: BrowserConfigIn
    multi_spec: MultiSpecConfigIn
    listing: ListingConfigIn
    delist: DelistConfigIn
    batch: BatchConfigIn


class RuntimeConfigUpdateIn(RuntimeConfigOut):
    pass

"""配置相关 API 模型。"""

from pydantic import BaseModel, Field, field_validator


class AccountOut(BaseModel):
    account_id: str
    enabled: bool
    phone: str = ""
    username: str = ""
    login_mode: str = "sms"
    shop_display_name: str = ""
    display_name: str = ""
    has_password: bool = False
    product_codes: list[str] = Field(default_factory=list)


class AccountDetailOut(AccountOut):
    password: str = ""


class AccountCreateIn(BaseModel):
    account_id: str = Field(..., min_length=1, max_length=64)
    enabled: bool = True
    phone: str = ""
    username: str = ""
    password: str = ""
    login_mode: str = "sms"
    product_codes: list[str] = Field(default_factory=list)

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("店铺 ID 不能为空")
        return v


class AccountUpdateIn(BaseModel):
    enabled: bool = True
    phone: str = ""
    username: str = ""
    password: str = ""
    login_mode: str = "sms"
    product_codes: list[str] = Field(default_factory=list)


class ConfigSummaryOut(BaseModel):
    app_name: str
    log_level: str
    assets_root: str
    excel_path: str
    llm_configured: bool
    database_configured: bool = False
    database_available: bool = False
    database_error: str = ""
    database_name: str = ""
    account_count: int
    enabled_account_count: int


class AppConfigIn(BaseModel):
    name: str = "dy-agent-platform"
    log_level: str = "INFO"


class LoginConfigIn(BaseModel):
    sms_wait_seconds: int = 300
    auto_send_sms: bool = True


class PathsConfigIn(BaseModel):
    assets_root: str = "data/assets/商品上架规格文件"
    profiles_root: str = "data/profiles"
    runs_root: str = "data/runs"


class BrowserConfigIn(BaseModel):
    headless: bool = False
    slow_mo: int = 0
    default_timeout_ms: int = 30_000
    base_url: str = "https://fxg.jinritemai.com"
    channel: str = ""


class MultiSpecConfigIn(BaseModel):
    excel: str = "data/assets/抖音所有商品.xls"
    defaults: dict[str, str] = Field(default_factory=dict)


class ListingConfigIn(BaseModel):
    category_keyword: str = "玩偶"
    title_mode: str = "page_ai"
    brand_name: str = "无品牌"
    manufacturer_name: str = ""
    slot_alignment_test: bool = False
    spec_fill_verify_test: bool = True
    primary_style_first_test: bool = True
    category_next_burst_demo: bool = True
    accessory_cost_pricing: bool = True
    accessory_tiered_float: bool = True


class RuntimeConfigOut(BaseModel):
    app: AppConfigIn
    login: LoginConfigIn
    paths: PathsConfigIn
    browser: BrowserConfigIn
    multi_spec: MultiSpecConfigIn
    listing: ListingConfigIn


class RuntimeConfigUpdateIn(RuntimeConfigOut):
    pass

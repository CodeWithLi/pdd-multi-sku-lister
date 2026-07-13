"""应用配置加载：YAML 业务配置 + .env 环境项。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource

from dy_agent.paths import DEFAULT_SETTINGS_PATH, PROJECT_ROOT

_RUNTIME_PROFILES = frozenset({"prod", "test"})


def resolve_env_file() -> str:
    override = (os.getenv("DY_ENV_FILE") or "").strip()
    if override:
        return override
    return str(PROJECT_ROOT / ".env")


class LoginConfig(BaseModel):
    """登录流程参数。"""

    sms_wait_seconds: int = 300
    auto_send_sms: bool = True


class AccountConfig(BaseModel):
    """单个抖店店铺账号。"""

    account_id: str
    enabled: bool = True
    phone: str = ""  # 手机验证码登录（当前默认）
    username: str = ""  # 预留：邮箱/账号密码登录
    password: str = ""
    login_mode: str = "sms"  # sms | email_password（后续）
    product_codes: list[str] = Field(default_factory=list)


class BrowserConfig(BaseModel):
    """Playwright 浏览器默认参数。"""

    headless: bool = False
    slow_mo: int = 0
    default_timeout_ms: int = 30_000
    base_url: str = "https://fxg.jinritemai.com"
    channel: str = ""


class PathsConfig(BaseModel):
    """运行时目录（相对 PROJECT_ROOT）。"""

    assets_root: str = "data/assets/商品上架规格文件"
    profiles_root: str = "data/profiles"
    runs_root: str = "data/runs"

    def resolve(self, key: str) -> Path:
        rel = getattr(self, key)
        return (PROJECT_ROOT / rel).resolve()


class MultiSpecConfig(BaseModel):
    """多规格上架：商品表路径与默认价格/库存。"""

    excel: str = "data/assets/抖音所有商品.xls"
    defaults: dict[str, str] = Field(default_factory=dict)

    @property
    def excel_path(self) -> Path:
        return (PROJECT_ROOT / self.excel).resolve()


class ListingConfig(BaseModel):
    """上架页默认参数与试验开关（对齐拼多多 pipeline）。"""

    category_keyword: str = "玩偶"
    title_mode: str = "page_ai"
    slot_alignment_test: bool = False
    spec_fill_verify_test: bool = True
    primary_style_first_test: bool = True
    category_next_burst_demo: bool = True
    accessory_cost_pricing: bool = True
    accessory_tiered_float: bool = True


class YamlSettings(BaseModel):
    """config/settings.yaml 的完整结构。"""

    app: dict[str, Any] = Field(default_factory=dict)
    login: LoginConfig = Field(default_factory=LoginConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    multi_spec: MultiSpecConfig = Field(default_factory=MultiSpecConfig)
    listing: ListingConfig = Field(default_factory=ListingConfig)
    accounts: list[AccountConfig] = Field(default_factory=list)


class EnvSettings(BaseSettings):
    """从 .env 读取的环境变量。"""

    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4-flash"
    orchestrator_model: str = ""
    playwright_headless: bool = False
    playwright_slow_mo: int = 0
    playwright_channel: str = ""
    dy_data_dir: str = "data"
    dy_config_path: str = str(DEFAULT_SETTINGS_PATH)
    dy_runtime_profile: str = "prod"
    database_url: str = ""
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout: int = 30

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            DotEnvSettingsSource(settings_cls, env_file=resolve_env_file()),
            file_secret_settings,
        )


def load_yaml_settings(path: Path | None = None) -> YamlSettings:
    cfg_path = path or Path(os.getenv("DY_CONFIG_PATH", DEFAULT_SETTINGS_PATH))
    if not cfg_path.is_file():
        return YamlSettings()
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return YamlSettings.model_validate(raw)


@lru_cache
def get_env_settings() -> EnvSettings:
    return EnvSettings()


def get_runtime_profile() -> str:
    profile = (get_env_settings().dy_runtime_profile or "prod").strip().lower()
    return profile if profile in _RUNTIME_PROFILES else "prod"


def get_database_name() -> str:
    url = (get_env_settings().database_url or "").strip()
    if not url:
        return ""
    try:
        from sqlalchemy.engine import make_url

        return str(make_url(url).database or "")
    except Exception:
        return ""


def save_yaml_settings(settings: YamlSettings, path: Path | None = None) -> None:
    cfg_path = path or Path(os.getenv("DY_CONFIG_PATH", DEFAULT_SETTINGS_PATH))
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = settings.model_dump(mode="python")
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_account(settings: YamlSettings, account_id: str) -> AccountConfig | None:
    """兼容旧调用；优先走 repositories.get_account_config。"""
    from dy_agent.db.repositories import get_account_config

    return get_account_config(settings, account_id)

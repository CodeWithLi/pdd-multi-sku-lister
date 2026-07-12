"""应用配置加载：YAML 业务配置 + .env 敏感/环境项。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource

from pdd_agent.paths import DEFAULT_SETTINGS_PATH, PROJECT_ROOT

_RUNTIME_PROFILES = frozenset({"prod", "test"})


def resolve_env_file() -> str:
    """优先 PDD_ENV_FILE，否则 myTest/.env。"""
    override = (os.getenv("PDD_ENV_FILE") or "").strip()
    if override:
        return override
    return str(PROJECT_ROOT / ".env")


class AccountConfig(BaseModel):
    """单个拼多多店铺账号。"""

    account_id: str
    enabled: bool = True
    username: str = ""
    password: str = ""
    product_codes: list[str] = Field(default_factory=list)  # 多规格商品编码列表


class BrowserConfig(BaseModel):
    """Playwright 浏览器默认参数。"""

    headless: bool = False
    slow_mo: int = 0  # 每步延迟(ms)，调试时可加大
    default_timeout_ms: int = 30_000
    base_url: str = "https://mms.pinduoduo.com"
    # 留空 = Playwright 自带 Chromium（服务器部署）；填 chrome = 本机 Google Chrome
    channel: str = ""


class PathsConfig(BaseModel):
    """运行时目录（相对 PROJECT_ROOT）。"""

    assets_root: str = "data/assets/商品上架规格文件"
    profiles_root: str = "data/profiles"
    runs_root: str = "data/runs"

    def resolve(self, key: str) -> Path:
        """将配置项解析为绝对路径。"""
        rel = getattr(self, key)
        return (PROJECT_ROOT / rel).resolve()


class MultiSpecConfig(BaseModel):
    """多规格上架：商品表路径与默认价格/库存。"""

    excel: str = "data/assets/拼多多所有商品.xls"
    defaults: dict[str, str] = Field(default_factory=dict)

    @property
    def excel_path(self) -> Path:
        return (PROJECT_ROOT / self.excel).resolve()


class ListingConfig(BaseModel):
    """上架页默认参数。"""

    category_keyword: str = "玩偶"
    title_mode: str = "page_ai"


class DelistConfig(BaseModel):
    """下架任务默认参数。"""

    min_created_after: str = ""
    dry_run: bool = True
    merchant_code_contains: str = ""
    max_delist_per_run: int = 50
    account_ids: list[str] = Field(default_factory=list)


class BatchConfig(BaseModel):
    """Batch task defaults."""

    max_concurrent_stores: int = Field(default=3, ge=1, le=5)
    store_start_delay_min_seconds: int = Field(default=30, ge=0, le=3600)
    store_start_delay_max_seconds: int = Field(default=180, ge=0, le=3600)
    activity_schedule_jitter_max_seconds: int = Field(default=1800, ge=0, le=7200)

    @model_validator(mode="after")
    def validate_delay_range(self) -> "BatchConfig":
        if self.store_start_delay_max_seconds < self.store_start_delay_min_seconds:
            self.store_start_delay_max_seconds = self.store_start_delay_min_seconds
        return self


class PipelineConfig(BaseModel):
    """整合链路全局策略（settings.yaml pipeline 段）。"""

    # 限时失败跳过活动仍推广时，推广商品 ID 来源：
    # listing_success = 上架成功的商品；limited_time_success = 限时提交成功的商品
    lt_failure_skip_activity_promotion_product_source: str = "listing_success"

    @model_validator(mode="after")
    def validate_promotion_product_source(self) -> "PipelineConfig":
        allowed = {"listing_success", "limited_time_success"}
        value = str(self.lt_failure_skip_activity_promotion_product_source or "").strip()
        if value not in allowed:
            self.lt_failure_skip_activity_promotion_product_source = "listing_success"
        else:
            self.lt_failure_skip_activity_promotion_product_source = value
        return self


class YamlSettings(BaseModel):
    """config/settings.yaml 的完整结构。"""

    app: dict[str, Any] = Field(default_factory=dict)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    multi_spec: MultiSpecConfig = Field(default_factory=MultiSpecConfig)
    listing: ListingConfig = Field(default_factory=ListingConfig)
    delist: DelistConfig = Field(default_factory=DelistConfig)
    batch: BatchConfig = Field(default_factory=BatchConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    accounts: list[AccountConfig] = Field(default_factory=list)


class EnvSettings(BaseSettings):
    """从 .env 读取的环境变量（API Key、Playwright 开关等）。"""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4-flash"
    orchestrator_model: str = ""  # 为空则与 llm_model 相同
    vision_model: str = ""  # 视觉识别（款式颜色），默认 glm-4v-flash
    playwright_headless: bool = False
    playwright_slow_mo: int = 0
    playwright_channel: str = ""  # 非空时覆盖 settings.yaml 的 browser.channel
    pdd_data_dir: str = "data"
    pdd_config_path: str = str(DEFAULT_SETTINGS_PATH)
    database_url: str = ""
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout: int = 30
    # prod=正式实例；test=本地 8011 测试实例（与正式库隔离）
    pdd_runtime_profile: str = "prod"
    # false 时仅保留 API + 任务队列 worker，不启动定时任务 / RabbitMQ 消费者
    pdd_background_jobs: bool = True

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 每次实例化时解析 env 文件，支持 PDD_ENV_FILE 指向 .env.test
        return (
            init_settings,
            env_settings,
            DotEnvSettingsSource(settings_cls, env_file=resolve_env_file()),
            file_secret_settings,
        )


def load_yaml_settings(path: Path | None = None) -> YamlSettings:
    """加载 YAML；文件不存在时返回空默认配置。"""
    cfg_path = path or Path(os.getenv("PDD_CONFIG_PATH", DEFAULT_SETTINGS_PATH))
    if not cfg_path.is_file():
        return YamlSettings()
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return YamlSettings.model_validate(raw)


@lru_cache
def get_env_settings() -> EnvSettings:
    """缓存环境配置，避免重复读 .env。"""
    return EnvSettings()


def get_runtime_profile() -> str:
    """运行环境标识：prod 或 test。"""
    profile = (get_env_settings().pdd_runtime_profile or "prod").strip().lower()
    return profile if profile in _RUNTIME_PROFILES else "prod"


def background_jobs_enabled() -> bool:
    """是否启动后台定时任务与 RabbitMQ 消费者。"""
    return bool(get_env_settings().pdd_background_jobs)


def get_database_name() -> str:
    """从 DATABASE_URL 解析库名，便于日志与健康检查展示。"""
    url = (get_env_settings().database_url or "").strip()
    if not url:
        return ""
    try:
        from sqlalchemy.engine import make_url

        return str(make_url(url).database or "")
    except Exception:
        return ""


def get_account(settings: YamlSettings, account_id: str) -> AccountConfig | None:
    """按 account_id 查找店铺配置。"""
    for acc in settings.accounts:
        if acc.account_id == account_id:
            return acc
    return None


def save_yaml_settings(settings: YamlSettings, path: Path | None = None) -> None:
    """将配置写回 settings.yaml。"""
    cfg_path = path or Path(os.getenv("PDD_CONFIG_PATH", DEFAULT_SETTINGS_PATH))
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = settings.model_dump(mode="python")
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

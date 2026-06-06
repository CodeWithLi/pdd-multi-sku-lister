"""应用配置加载：YAML 业务配置 + .env 敏感/环境项。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from pdd_agent.paths import DEFAULT_SETTINGS_PATH, PROJECT_ROOT


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


class PathsConfig(BaseModel):
    """运行时目录（相对 PROJECT_ROOT）。"""

    assets_root: str = "data/assets"
    profiles_root: str = "data/profiles"
    runs_root: str = "data/runs"

    def resolve(self, key: str) -> Path:
        """将配置项解析为绝对路径。"""
        rel = getattr(self, key)
        return (PROJECT_ROOT / rel).resolve()


class MultiSpecConfig(BaseModel):
    """多规格上架：Excel 路径与默认价格/库存。"""

    excel: str = "data/assets/sku+名称.xlsx"
    defaults: dict[str, str] = Field(default_factory=dict)

    @property
    def excel_path(self) -> Path:
        return (PROJECT_ROOT / self.excel).resolve()


class YamlSettings(BaseModel):
    """config/settings.yaml 的完整结构。"""

    app: dict[str, Any] = Field(default_factory=dict)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    multi_spec: MultiSpecConfig = Field(default_factory=MultiSpecConfig)
    accounts: list[AccountConfig] = Field(default_factory=list)


class EnvSettings(BaseSettings):
    """从 .env 读取的环境变量（API Key、Playwright 开关等）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4-flash"
    orchestrator_model: str = ""  # 为空则与 llm_model 相同
    playwright_headless: bool = False
    playwright_slow_mo: int = 0
    pdd_data_dir: str = "data"
    pdd_config_path: str = str(DEFAULT_SETTINGS_PATH)


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


def get_account(settings: YamlSettings, account_id: str) -> AccountConfig | None:
    """按 account_id 查找店铺配置。"""
    for acc in settings.accounts:
        if acc.account_id == account_id:
            return acc
    return None

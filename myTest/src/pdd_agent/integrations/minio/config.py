"""MinIO 集成配置（独立 YAML，不写入 settings.yaml）。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from pdd_agent.paths import CONFIG_DIR, PROJECT_ROOT

DEFAULT_MINIO_CONFIG_PATH = CONFIG_DIR / "minio.yaml"


class MinioRabbitMQConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 5672
    username: str = "guest"
    password: str = "guest"
    queue: str = "minio-upload-events"
    settle_seconds: int = Field(default=100, ge=0, le=600)


class MinioYamlConfig(BaseModel):
    enabled: bool = True
    endpoint: str = "127.0.0.1:9000"
    secure: bool = False
    access_key: str = ""
    secret_key: str = ""
    bucket: str = ""
    categories: list[str] = Field(default_factory=lambda: ["笔袋"])
    prefix: str = ""
    listing_poll_seconds: int = Field(default=30, ge=0, le=300)
    cache_root: str = Field(
        default="data/minio_cache/商品上架规格文件",
        description="MinIO 素材同步到本地的缓存目录（相对 myTest 根目录）",
    )
    alist_url: str = Field(default="", description="Alist 运营上传入口（仅供参考）")
    console_url: str = Field(default="", description="MinIO 控制台地址（仅供参考）")
    rabbitmq: MinioRabbitMQConfig = Field(default_factory=MinioRabbitMQConfig)


class MinioConfig(BaseModel):
    enabled: bool = True
    endpoint: str = "127.0.0.1:9000"
    secure: bool = False
    access_key: str = ""
    secret_key: str = ""
    bucket: str = ""
    categories: list[str] = Field(default_factory=lambda: ["笔袋"])
    prefix: str = ""
    listing_poll_seconds: int = 30
    cache_root: str = "data/minio_cache/商品上架规格文件"
    alist_url: str = ""
    console_url: str = ""
    rabbitmq: MinioRabbitMQConfig = Field(default_factory=MinioRabbitMQConfig)


class MinioEnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = ""


@lru_cache
def get_minio_env_settings() -> MinioEnvSettings:
    return MinioEnvSettings()


def load_minio_config(path: Path | None = None) -> MinioConfig:
    """合并 minio.yaml 与 .env 中的 MinIO 凭据。"""
    cfg_path = path or Path(os.getenv("MINIO_CONFIG_PATH", DEFAULT_MINIO_CONFIG_PATH))
    raw: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    yaml_cfg = MinioYamlConfig.model_validate(raw)
    env = get_minio_env_settings()

    rabbitmq = yaml_cfg.rabbitmq
    if "rabbitmq" in raw and isinstance(raw.get("rabbitmq"), dict):
        rabbitmq = MinioRabbitMQConfig.model_validate(raw["rabbitmq"])

    return MinioConfig(
        enabled=bool(yaml_cfg.enabled),
        endpoint=(env.minio_endpoint or yaml_cfg.endpoint).strip(),
        secure=bool(yaml_cfg.secure),
        access_key=(env.minio_access_key or yaml_cfg.access_key).strip(),
        secret_key=(env.minio_secret_key or yaml_cfg.secret_key).strip(),
        bucket=(env.minio_bucket or yaml_cfg.bucket).strip(),
        categories=[str(item).strip() for item in yaml_cfg.categories if str(item).strip()],
        prefix=str(yaml_cfg.prefix or "").strip().strip("/"),
        listing_poll_seconds=int(yaml_cfg.listing_poll_seconds or 0),
        cache_root=str(yaml_cfg.cache_root or "data/minio_cache/商品上架规格文件").strip(),
        alist_url=str(yaml_cfg.alist_url or "").strip(),
        console_url=str(yaml_cfg.console_url or "").strip(),
        rabbitmq=rabbitmq,
    )


def minio_cache_root(config: MinioConfig | None = None) -> Path:
    from pdd_agent.paths import PROJECT_ROOT

    cfg = config or load_minio_config()
    rel = str(cfg.cache_root or "data/minio_cache/商品上架规格文件").strip()
    return (PROJECT_ROOT / rel).resolve()


def minio_configured(config: MinioConfig | None = None) -> bool:
    cfg = config or load_minio_config()
    return bool(cfg.enabled and cfg.endpoint and cfg.access_key and cfg.secret_key and cfg.bucket)


def minio_scan_prefixes(config: MinioConfig | None = None) -> list[str]:
    cfg = config or load_minio_config()
    prefixes: list[str] = []
    if cfg.prefix:
        prefixes.append(cfg.prefix.strip("/") + "/")
        return prefixes
    for category in cfg.categories:
        category = str(category or "").strip().strip("/")
        if category:
            prefixes.append(f"{category}/")
    return prefixes or [""]

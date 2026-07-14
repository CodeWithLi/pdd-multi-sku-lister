"""MinIO integration config (standalone YAML, not in settings.yaml)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from dy_agent.paths import CONFIG_DIR, PROJECT_ROOT

DEFAULT_MINIO_CONFIG_PATH = CONFIG_DIR / "minio.yaml"
MinioRefreshMode = Literal["poll", "rabbitmq"]
DEFAULT_DY_RABBITMQ_QUEUE = "beilemei.dy.image.ingest"


class AlistConfig(BaseModel):
    enabled: bool = True
    url: str = ""
    username: str = "admin"
    password: str = ""
    root_path: str = Field(default="/公司电商主图库")
    verify_ssl: bool = False
    timeout_seconds: int = Field(default=60, ge=5, le=300)


class MinioRabbitMQConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 5672
    management_port: int = Field(default=15672, ge=1, le=65535)
    username: str = "guest"
    password: str = "guest"
    queue: str = DEFAULT_DY_RABBITMQ_QUEUE
    exchange: str = "minio.events"
    routing_key: str = "beilemei.images"
    settle_seconds: int = Field(default=100, ge=0, le=600)


class MinioYamlConfig(BaseModel):
    refresh_mode: MinioRefreshMode = "poll"
    enabled: bool = True
    endpoint: str = "127.0.0.1:9000"
    secure: bool = False
    access_key: str = ""
    secret_key: str = ""
    bucket: str = ""
    categories: list[str] = Field(default_factory=lambda: ["笔袋"])
    prefix: str = ""
    listing_poll_seconds: int = Field(default=30, ge=0, le=300)
    default_material_source: str = "minio"
    cache_root: str = "data/minio_cache/商品上架规格文件"
    alist_url: str = ""
    alist: AlistConfig = Field(default_factory=AlistConfig)
    console_url: str = ""
    rabbitmq: MinioRabbitMQConfig = Field(default_factory=MinioRabbitMQConfig)


class MinioConfig(BaseModel):
    refresh_mode: MinioRefreshMode = "poll"
    enabled: bool = True
    endpoint: str = "127.0.0.1:9000"
    secure: bool = False
    access_key: str = ""
    secret_key: str = ""
    bucket: str = ""
    categories: list[str] = Field(default_factory=lambda: ["笔袋"])
    prefix: str = ""
    listing_poll_seconds: int = 30
    default_material_source: str = "minio"
    cache_root: str = "data/minio_cache/商品上架规格文件"
    alist_url: str = ""
    alist: AlistConfig = Field(default_factory=AlistConfig)
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
    rabbitmq_username: str = ""
    rabbitmq_password: str = ""
    alist_url: str = ""
    alist_username: str = ""
    alist_password: str = ""


@lru_cache
def get_minio_env_settings() -> MinioEnvSettings:
    return MinioEnvSettings()


def load_minio_config(path: Path | None = None) -> MinioConfig:
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

    alist = yaml_cfg.alist
    if "alist" in raw and isinstance(raw.get("alist"), dict):
        alist = AlistConfig.model_validate(raw["alist"])
    alist_url = (env.alist_url or yaml_cfg.alist_url or alist.url).strip()
    if alist_url and not alist.url:
        alist = alist.model_copy(update={"url": alist_url})
    alist = alist.model_copy(
        update={
            "username": (env.alist_username or alist.username).strip(),
            "password": (env.alist_password or alist.password).strip(),
        }
    )

    refresh_mode = str(yaml_cfg.refresh_mode or "poll").strip().lower()
    if refresh_mode not in {"poll", "rabbitmq"}:
        refresh_mode = "poll"

    return MinioConfig(
        refresh_mode=refresh_mode,  # type: ignore[arg-type]
        enabled=bool(yaml_cfg.enabled),
        endpoint=(env.minio_endpoint or yaml_cfg.endpoint).strip(),
        secure=bool(yaml_cfg.secure),
        access_key=(env.minio_access_key or yaml_cfg.access_key).strip(),
        secret_key=(env.minio_secret_key or yaml_cfg.secret_key).strip(),
        bucket=(env.minio_bucket or yaml_cfg.bucket).strip(),
        categories=[str(item).strip() for item in yaml_cfg.categories if str(item).strip()],
        prefix=str(yaml_cfg.prefix or "").strip().strip("/"),
        listing_poll_seconds=int(yaml_cfg.listing_poll_seconds or 0),
        default_material_source=str(yaml_cfg.default_material_source or "minio").strip().lower(),
        cache_root=str(yaml_cfg.cache_root or "data/minio_cache/商品上架规格文件").strip(),
        alist_url=(alist_url or str(yaml_cfg.alist_url or "").strip()),
        alist=alist,
        console_url=str(yaml_cfg.console_url or "").strip(),
        rabbitmq=rabbitmq.model_copy(
            update={
                "username": (env.rabbitmq_username or rabbitmq.username).strip(),
                "password": (env.rabbitmq_password or rabbitmq.password).strip(),
            }
        ),
    )


def minio_cache_root(config: MinioConfig | None = None) -> Path:
    cfg = config or load_minio_config()
    rel = str(cfg.cache_root or "data/minio_cache/商品上架规格文件").strip()
    return (PROJECT_ROOT / rel).resolve()


def minio_configured(config: MinioConfig | None = None) -> bool:
    cfg = config or load_minio_config()
    return bool(cfg.enabled and cfg.endpoint and cfg.access_key and cfg.secret_key and cfg.bucket)


def minio_refresh_mode(config: MinioConfig | None = None) -> MinioRefreshMode:
    cfg = config or load_minio_config()
    mode = str(cfg.refresh_mode or "poll").strip().lower()
    return "rabbitmq" if mode == "rabbitmq" else "poll"


def minio_poll_interval_seconds(config: MinioConfig | None = None) -> int:
    cfg = config or load_minio_config()
    if minio_refresh_mode(cfg) == "rabbitmq":
        return 0
    return max(0, int(cfg.listing_poll_seconds or 0))


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

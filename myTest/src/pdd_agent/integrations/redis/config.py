"""Redis 配置（独立 YAML）。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from pdd_agent.paths import CONFIG_DIR, PROJECT_ROOT

DEFAULT_REDIS_CONFIG_PATH = CONFIG_DIR / "redis.yaml"


class RedisYamlConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 6379
    password: str = ""
    db: int = Field(default=0, ge=0, le=15)
    key_prefix: str = "pdd"


class RedisConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 6379
    password: str = ""
    db: int = 0
    key_prefix: str = "pdd"


class RedisEnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_host: str = ""
    redis_port: int = 0
    redis_password: str = ""
    redis_db: int = -1


@lru_cache
def load_redis_config(path: Path | None = None) -> RedisConfig:
    config_path = path or DEFAULT_REDIS_CONFIG_PATH
    yaml_cfg = RedisYamlConfig()
    if config_path.is_file():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            yaml_cfg = RedisYamlConfig.model_validate(raw)

    env = RedisEnvSettings()
    return RedisConfig(
        enabled=bool(yaml_cfg.enabled),
        host=str(env.redis_host or yaml_cfg.host or "127.0.0.1").strip(),
        port=int(env.redis_port or yaml_cfg.port or 6379),
        password=str(env.redis_password if env.redis_password else yaml_cfg.password or ""),
        db=int(env.redis_db if env.redis_db >= 0 else yaml_cfg.db),
        key_prefix=str(yaml_cfg.key_prefix or "pdd").strip() or "pdd",
    )


def redis_configured(config: RedisConfig | None = None) -> bool:
    cfg = config or load_redis_config()
    return bool(cfg.enabled and cfg.host and cfg.port)

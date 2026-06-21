"""Redis 客户端（懒连接，失败时返回 None）。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.redis.config import RedisConfig, load_redis_config, redis_configured

logger = get_logger(__name__)

_CLIENT: Any | None = None
_CLIENT_ERROR: str = ""


def _build_client(cfg: RedisConfig):
    import redis

    return redis.Redis(
        host=cfg.host,
        port=int(cfg.port),
        password=cfg.password or None,
        db=int(cfg.db),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=5,
    )


def get_redis_client(*, force_new: bool = False):
    """返回 Redis 客户端；不可用时返回 None。"""
    global _CLIENT, _CLIENT_ERROR

    cfg = load_redis_config()
    if not redis_configured(cfg):
        return None

    if force_new:
        try:
            client = _build_client(cfg)
            client.ping()
            return client
        except Exception as exc:
            logger.warning("redis connect failed: %s", exc)
            return None

    if _CLIENT is not None:
        return _CLIENT

    try:
        client = _build_client(cfg)
        client.ping()
        _CLIENT = client
        _CLIENT_ERROR = ""
        logger.info("redis connected host=%s port=%s db=%s", cfg.host, cfg.port, cfg.db)
        return _CLIENT
    except Exception as exc:
        _CLIENT_ERROR = str(exc)
        logger.warning("redis connect failed: %s", exc)
        return None


def check_redis_health(config: RedisConfig | None = None) -> dict[str, Any]:
    cfg = config or load_redis_config()
    if not redis_configured(cfg):
        return {"available": False, "error": "Redis 未启用或未配置"}
    client = get_redis_client(force_new=True)
    if client is None:
        return {
            "available": False,
            "error": _CLIENT_ERROR or "Redis 连接失败",
            "host": cfg.host,
            "port": cfg.port,
            "db": cfg.db,
        }
    try:
        client.ping()
        return {
            "available": True,
            "host": cfg.host,
            "port": cfg.port,
            "db": cfg.db,
            "key_prefix": cfg.key_prefix,
        }
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "host": cfg.host,
            "port": cfg.port,
            "db": cfg.db,
        }


def reset_redis_client_cache() -> None:
    global _CLIENT, _CLIENT_ERROR
    _CLIENT = None
    _CLIENT_ERROR = ""

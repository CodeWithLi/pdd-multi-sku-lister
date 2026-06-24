"""MinIO 客户端封装。"""

from __future__ import annotations

from minio import Minio
from minio.error import S3Error

from pdd_agent.integrations.minio.config import (
    MinioConfig,
    load_minio_config,
    minio_configured,
    minio_poll_interval_seconds,
    minio_refresh_mode,
    minio_scan_prefixes,
)


class MinioAPIError(RuntimeError):
    pass


def get_minio_client(config: MinioConfig | None = None) -> Minio:
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        raise MinioAPIError("MinIO 未配置：请填写 config/minio.yaml 或 .env 中的 MINIO_*")
    return Minio(
        cfg.endpoint,
        access_key=cfg.access_key,
        secret_key=cfg.secret_key,
        secure=cfg.secure,
    )


def check_minio_health(config: MinioConfig | None = None) -> dict:
    """测试 MinIO 连接与 bucket 是否可访问。"""
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        return {
            "configured": False,
            "available": False,
            "error": "MinIO 未配置",
        }
    try:
        client = get_minio_client(cfg)
        if not client.bucket_exists(cfg.bucket):
            return {
                "configured": True,
                "available": False,
                "bucket": cfg.bucket,
                "error": f"bucket 不存在: {cfg.bucket}",
            }
        object_sample_found = False
        for _ in client.list_objects(cfg.bucket, prefix=minio_scan_prefixes(cfg)[0], recursive=True):
            object_sample_found = True
            break
        return {
            "configured": True,
            "available": True,
            "endpoint": cfg.endpoint,
            "bucket": cfg.bucket,
            "categories": list(cfg.categories),
            "prefix": cfg.prefix,
            "refresh_mode": minio_refresh_mode(cfg),
            "listing_poll_seconds": minio_poll_interval_seconds(cfg),
            "object_sample_found": object_sample_found,
        }
    except S3Error as exc:
        return {
            "configured": True,
            "available": False,
            "bucket": cfg.bucket,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "configured": True,
            "available": False,
            "bucket": cfg.bucket,
            "error": str(exc),
        }

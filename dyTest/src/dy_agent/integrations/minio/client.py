"""MinIO client wrapper."""

from __future__ import annotations

from minio import Minio
from minio.error import S3Error

from dy_agent.integrations.minio.config import (
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
        prefixes = minio_scan_prefixes(cfg)
        for scan_prefix in prefixes:
            for _ in client.list_objects(cfg.bucket, prefix=scan_prefix, recursive=True):
                object_sample_found = True
                break
            if object_sample_found:
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
            "alist_url": cfg.alist_url or cfg.alist.url,
            "console_url": cfg.console_url,
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

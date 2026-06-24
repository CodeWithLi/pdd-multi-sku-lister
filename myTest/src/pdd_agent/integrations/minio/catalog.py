"""从 MinIO 扫描素材目录，输出与本地 catalog 一致的 ListingTargetOption。"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from pathlib import Path

from pdd_agent.integrations.minio.client import MinioAPIError, get_minio_client
from pdd_agent.integrations.minio.config import (
    MinioConfig,
    load_minio_config,
    minio_configured,
    minio_refresh_mode,
    minio_scan_prefixes,
)
from pdd_agent.integrations.minio.index import (
    MinioSetIndexRecord,
    is_minio_index_fresh,
    load_listing_targets_from_redis,
    object_prefix_from_object_key,
    resolve_minio_set_prefix,
    save_minio_index,
)
from pdd_agent.skills.listing.catalog import (
    IMAGE_EXTS,
    ListingTargetOption,
    _image_set_sort_key,
    is_image_set_dir,
)

PRODUCT_CODE_PATTERN = re.compile(r"^([A-Z0-9]+)")
IGNORED_OBJECT_SUFFIXES = ("/.alist",)
IGNORED_DIR_NAMES = frozenset({".alist", ".__jianying_export_temp_folder__"})


def extract_product_code(folder_name: str) -> str:
    """返回套图下商品文件夹名（与 MinIO/本地目录名一致，保留中文后缀）。"""
    name = str(folder_name or "").strip()
    if not name or name.startswith("."):
        return ""
    return name


def _numbered_image_index(filename: str) -> int | None:
    stem = Path(filename).stem.strip()
    if stem.isdigit():
        return int(stem)
    match = re.match(r"^主图(\d+)$", stem)
    if match:
        return int(match.group(1))
    return None


def _is_image_object_name(object_name: str) -> bool:
    if any(object_name.endswith(suffix) for suffix in IGNORED_OBJECT_SUFFIXES):
        return False
    if "/.alist" in object_name:
        return False
    return Path(object_name).suffix.lower() in IMAGE_EXTS


def _scan_prefixes(config: MinioConfig) -> list[str]:
    return minio_scan_prefixes(config)


def resolve_listing_path_parts(parts: list[str]) -> tuple[str, str, str] | None:
    """解析 object key 路径中的 family / image_set / product_folder。"""
    return _resolve_listing_path_parts(parts)


def _resolve_listing_path_parts(parts: list[str]) -> tuple[str, str, str] | None:
    """解析 object key 路径中的 family / image_set / product_folder。"""
    if len(parts) < 4:
        return None
    filename = parts[-1]
    if not _is_image_object_name(filename):
        return None

    for index in range(1, len(parts) - 2):
        image_set = parts[index]
        if not is_image_set_dir(image_set):
            continue
        family_code = parts[index - 1]
        product_folder = parts[index + 1]
        if not family_code or not product_folder:
            continue
        if family_code in IGNORED_DIR_NAMES or product_folder in IGNORED_DIR_NAMES:
            continue
        return family_code, image_set, product_folder
    return None


_LISTING_TARGETS_CACHE: dict[str, object] = {
    "loaded_at": 0.0,
    "targets": None,
    "config_key": "",
}


def _listing_targets_cache_key(cfg: MinioConfig) -> str:
    prefixes = ",".join(_scan_prefixes(cfg))
    return f"{cfg.bucket}|{cfg.endpoint}|{prefixes}"


def clear_minio_listing_targets_cache() -> None:
    _LISTING_TARGETS_CACHE["loaded_at"] = 0.0
    _LISTING_TARGETS_CACHE["targets"] = None
    _LISTING_TARGETS_CACHE["config_key"] = ""


def _scan_minio_listing_targets(cfg: MinioConfig) -> tuple[list[ListingTargetOption], list[MinioSetIndexRecord]]:
    client = get_minio_client(cfg)
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    prefixes: dict[tuple[str, str], str] = {}

    for scan_prefix in _scan_prefixes(cfg):
        for obj in client.list_objects(cfg.bucket, prefix=scan_prefix, recursive=True):
            parts = obj.object_name.split("/")
            resolved = _resolve_listing_path_parts(parts)
            if not resolved:
                continue
            family_code, image_set, product_folder = resolved
            product_code = extract_product_code(product_folder)
            if not product_code:
                continue
            key = (family_code, image_set)
            grouped[key].add(product_code)
            if key not in prefixes:
                prefixes[key] = object_prefix_from_object_key(obj.object_name, family_code, image_set)

    targets: list[ListingTargetOption] = []
    records: list[MinioSetIndexRecord] = []
    for (family_code, image_set), codes in sorted(
        grouped.items(),
        key=lambda item: (item[0][0], _image_set_sort_key(item[0][1])),
    ):
        sorted_codes = tuple(sorted(codes))
        selector = f"{family_code}/{image_set}"
        targets.append(
            ListingTargetOption(
                selector=selector,
                family_code=family_code,
                image_set=image_set,
                product_codes=list(sorted_codes),
            )
        )
        records.append(
            MinioSetIndexRecord(
                selector=selector,
                family_code=family_code,
                image_set=image_set,
                object_prefix=prefixes.get((family_code, image_set), f"{family_code}/{image_set}/"),
                product_codes=sorted_codes,
            )
        )
    return targets, records


def list_minio_listing_targets(
    config: MinioConfig | None = None,
    *,
    force_refresh: bool = False,
) -> list[ListingTargetOption]:
    """读取套图列表：优先 Redis 索引，过期后 list MinIO 元数据并回写 Redis。"""
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        return []

    cache_seconds = max(0, int(cfg.listing_poll_seconds or 0))
    if minio_refresh_mode(cfg) == "rabbitmq":
        cache_seconds = 0
    cache_key = _listing_targets_cache_key(cfg)

    if not force_refresh and minio_refresh_mode(cfg) == "rabbitmq":
        redis_targets = load_listing_targets_from_redis(cfg)
        if redis_targets is not None:
            _LISTING_TARGETS_CACHE["loaded_at"] = time.time()
            _LISTING_TARGETS_CACHE["targets"] = redis_targets
            _LISTING_TARGETS_CACHE["config_key"] = cache_key
            return list(redis_targets)

    if not force_refresh and cache_seconds > 0:
        cached_targets = _LISTING_TARGETS_CACHE.get("targets")
        loaded_at = float(_LISTING_TARGETS_CACHE.get("loaded_at") or 0.0)
        if (
            cached_targets is not None
            and _LISTING_TARGETS_CACHE.get("config_key") == cache_key
            and time.time() - loaded_at < cache_seconds
        ):
            return list(cached_targets)

        if is_minio_index_fresh(cfg, cache_seconds=cache_seconds):
            redis_targets = load_listing_targets_from_redis(cfg)
            if redis_targets is not None:
                _LISTING_TARGETS_CACHE["loaded_at"] = time.time()
                _LISTING_TARGETS_CACHE["targets"] = redis_targets
                _LISTING_TARGETS_CACHE["config_key"] = cache_key
                return list(redis_targets)

    targets, records = _scan_minio_listing_targets(cfg)
    save_minio_index(cfg, records)
    _LISTING_TARGETS_CACHE["loaded_at"] = time.time()
    _LISTING_TARGETS_CACHE["targets"] = targets
    _LISTING_TARGETS_CACHE["config_key"] = cache_key
    return targets


def build_minio_catalog_set_index(config: MinioConfig | None = None) -> dict[str, frozenset[str]]:
    return {
        item.selector: frozenset(item.product_codes)
        for item in list_minio_listing_targets(config)
    }


def list_minio_objects_for_product(
    *,
    family_code: str,
    image_set: str,
    product_code: str,
    config: MinioConfig | None = None,
) -> list[str]:
    """列出某商品编码目录下的全部图片 object key（按 Redis 前缀精准 list，不扫全桶）。"""
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        raise MinioAPIError("MinIO 未配置")

    client = get_minio_client(cfg)
    product_code = str(product_code or "").strip()
    matched: list[str] = []

    object_prefix = resolve_minio_set_prefix(family_code, image_set, cfg)
    list_prefixes = [object_prefix] if object_prefix else []
    if not list_prefixes:
        suffix = f"{family_code}/{image_set}/"
        list_prefixes = [
            f"{scan_prefix}{suffix}" if scan_prefix else suffix
            for scan_prefix in _scan_prefixes(cfg)
        ]

    for list_prefix in list_prefixes:
        for obj in client.list_objects(cfg.bucket, prefix=list_prefix, recursive=True):
            key = obj.object_name
            if not _is_image_object_name(key):
                continue
            folder_name = key.split("/")[-2]
            if folder_name.strip() != product_code.strip():
                continue
            matched.append(key)
    return sorted(set(matched))

"""Scan MinIO bucket and produce listing target options."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from dy_agent.integrations.minio.client import get_minio_client
from dy_agent.integrations.minio.config import (
    MinioConfig,
    load_minio_config,
    minio_configured,
    minio_scan_prefixes,
)
from dy_agent.skills.listing.catalog import IMAGE_EXTS, is_image_set_dir

IGNORED_OBJECT_SUFFIXES = ("/.alist",)
IGNORED_DIR_NAMES = frozenset({".alist", ".__jianying_export_temp_folder__"})


@dataclass
class ListingTargetOption:
    selector: str
    family_code: str
    image_set: str
    product_codes: list[str] = field(default_factory=list)

    @property
    def product_count(self) -> int:
        return len(self.product_codes)


def extract_product_code(folder_name: str) -> str:
    name = str(folder_name or "").strip()
    if not name or name.startswith("."):
        return ""
    return name


def _is_image_object_name(object_name: str) -> bool:
    if any(object_name.endswith(suffix) for suffix in IGNORED_OBJECT_SUFFIXES):
        return False
    if "/.alist" in object_name:
        return False
    return Path(object_name).suffix.lower() in IMAGE_EXTS


def _scan_prefixes(config: MinioConfig) -> list[str]:
    return minio_scan_prefixes(config)


def _resolve_listing_path_parts(parts: list[str]) -> tuple[str, str, str] | None:
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


def _scan_minio_listing_targets(cfg: MinioConfig) -> list[ListingTargetOption]:
    client = get_minio_client(cfg)
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)

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
            grouped[(family_code, image_set)].add(product_code)

    targets: list[ListingTargetOption] = []
    for (family_code, image_set), codes in sorted(grouped.items()):
        sorted_codes = sorted(codes)
        targets.append(
            ListingTargetOption(
                selector=f"{family_code}/{image_set}",
                family_code=family_code,
                image_set=image_set,
                product_codes=sorted_codes,
            )
        )
    return targets


def list_minio_listing_targets(
    config: MinioConfig | None = None,
    *,
    force_refresh: bool = False,
) -> list[ListingTargetOption]:
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        return []

    cache_seconds = max(0, int(cfg.listing_poll_seconds or 0))
    cache_key = _listing_targets_cache_key(cfg)

    if not force_refresh and cache_seconds > 0:
        cached_targets = _LISTING_TARGETS_CACHE.get("targets")
        loaded_at = float(_LISTING_TARGETS_CACHE.get("loaded_at") or 0.0)
        if (
            cached_targets is not None
            and _LISTING_TARGETS_CACHE.get("config_key") == cache_key
            and time.time() - loaded_at < cache_seconds
        ):
            return list(cached_targets)  # type: ignore[arg-type]

    targets = _scan_minio_listing_targets(cfg)
    _LISTING_TARGETS_CACHE["loaded_at"] = time.time()
    _LISTING_TARGETS_CACHE["targets"] = targets
    _LISTING_TARGETS_CACHE["config_key"] = cache_key
    return targets


def build_minio_catalog_set_index(config: MinioConfig | None = None) -> dict[str, frozenset[str]]:
    return {
        item.selector: frozenset(item.product_codes)
        for item in list_minio_listing_targets(config)
    }

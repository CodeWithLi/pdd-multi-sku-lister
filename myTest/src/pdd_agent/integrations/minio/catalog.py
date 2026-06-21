"""从 MinIO 扫描素材目录，输出与本地 catalog 一致的 ListingTargetOption。"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from pdd_agent.integrations.minio.client import MinioAPIError, get_minio_client
from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config, minio_configured, minio_scan_prefixes
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
    """从 MinIO 商品文件夹名提取编码，如 BD021A卡皮巴拉笔袋 → BD021A。"""
    name = str(folder_name or "").strip()
    if not name or name.startswith("."):
        return ""
    match = PRODUCT_CODE_PATTERN.match(name)
    return match.group(1) if match else name


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


def _resolve_listing_path_parts(parts: list[str]) -> tuple[str, str, str] | None:
    """解析 object key 路径中的 family / image_set / product_folder。"""
    if len(parts) < 4:
        return None
    filename = parts[-1]
    if not _is_image_object_name(filename):
        return None
    if _numbered_image_index(filename) is None:
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


def list_minio_listing_targets(config: MinioConfig | None = None) -> list[ListingTargetOption]:
    """扫描 MinIO bucket，返回与本地 assets 相同结构的 listing targets。"""
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        return []

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
    for (family_code, image_set), codes in sorted(
        grouped.items(),
        key=lambda item: (item[0][0], _image_set_sort_key(item[0][1])),
    ):
        sorted_codes = tuple(sorted(codes))
        targets.append(
            ListingTargetOption(
                selector=f"{family_code}/{image_set}",
                family_code=family_code,
                image_set=image_set,
                product_codes=sorted_codes,
            )
        )
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
    """列出某商品编码目录下的全部图片 object key（供后续下载/上架使用）。"""
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        raise MinioAPIError("MinIO 未配置")

    client = get_minio_client(cfg)
    prefixes = _scan_prefixes(cfg)
    product_code = str(product_code or "").strip()
    suffix = f"/{family_code}/{image_set}/"
    matched: list[str] = []

    for scan_prefix in prefixes:
        for obj in client.list_objects(cfg.bucket, prefix=scan_prefix, recursive=True):
            key = obj.object_name
            if suffix not in key or not _is_image_object_name(key):
                continue
            folder_name = key.split("/")[-2]
            if extract_product_code(folder_name) != product_code:
                continue
            matched.append(key)
    return sorted(matched)

"""将 MinIO 素材同步到本地缓存，复用现有 catalog 解析逻辑。"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.catalog import (
    _is_image_object_name,
    _scan_prefixes,
    extract_product_code,
    list_minio_listing_targets,
)
from pdd_agent.integrations.minio.client import get_minio_client
from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config, minio_cache_root, minio_configured
from pdd_agent.skills.listing.catalog import is_image_set_dir

logger = get_logger(__name__)


def _resolve_image_set_folder(object_name: str) -> tuple[str, str, str] | None:
    """解析 object key -> (family_code, image_set, product_folder)。"""
    parts = object_name.split("/")
    if len(parts) < 5:
        return None
    if not _is_image_object_name(object_name):
        return None
    for index in range(1, len(parts) - 2):
        image_set = parts[index]
        if not is_image_set_dir(image_set):
            continue
        family_code = parts[index - 1]
        product_folder = parts[index + 1]
        if family_code and product_folder:
            return family_code, image_set, product_folder
    return None


def _sets_for_product_codes(product_codes: set[str], config: MinioConfig | None = None) -> set[tuple[str, str]]:
    selected = {str(code or "").strip().upper() for code in product_codes if str(code or "").strip()}
    if not selected:
        return set()
    sets: set[tuple[str, str]] = set()
    for target in list_minio_listing_targets(config):
        if any(code.upper() in selected for code in target.product_codes):
            sets.add((target.family_code, target.image_set))
    return sets


def stage_minio_image_set(
    *,
    family_code: str,
    image_set: str,
    config: MinioConfig | None = None,
    cache_root: Path | None = None,
) -> int:
    """下载某套图下全部兄弟商品文件夹到本地缓存，返回写入文件数。"""
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        return 0

    client = get_minio_client(cfg)
    dest_root = cache_root or minio_cache_root(cfg)
    marker = f"/{family_code}/{image_set}/"
    grouped: dict[str, list[str]] = defaultdict(list)

    for scan_prefix in _scan_prefixes(cfg):
        for obj in client.list_objects(cfg.bucket, prefix=scan_prefix, recursive=True):
            key = obj.object_name
            if marker not in key:
                continue
            resolved = _resolve_image_set_folder(key)
            if not resolved:
                continue
            resolved_family, resolved_set, product_folder = resolved
            if resolved_family != family_code or resolved_set != image_set:
                continue
            grouped[product_folder].append(key)

    written = 0
    for product_folder, keys in grouped.items():
        product_code = extract_product_code(product_folder)
        if not product_code:
            continue
        dest_dir = dest_root / family_code / image_set / product_code
        dest_dir.mkdir(parents=True, exist_ok=True)
        for key in keys:
            filename = key.split("/")[-1]
            dest_path = dest_dir / filename
            client.fget_object(cfg.bucket, key, str(dest_path))
            written += 1
    if written:
        logger.info(
            "minio staged set %s/%s -> %s files",
            family_code,
            image_set,
            written,
        )
    return written


def stage_minio_for_product_codes(product_codes: list[str], config: MinioConfig | None = None) -> Path:
    """按商品编码同步 MinIO 素材到本地缓存目录。"""
    cfg = config or load_minio_config()
    cache_root = minio_cache_root(cfg)
    cache_root.mkdir(parents=True, exist_ok=True)
    sets = _sets_for_product_codes(set(product_codes), cfg)
    total = 0
    for family_code, image_set in sorted(sets):
        total += stage_minio_image_set(
            family_code=family_code,
            image_set=image_set,
            config=cfg,
            cache_root=cache_root,
        )
    logger.info("minio staged product_codes=%s sets=%s files=%s", product_codes, len(sets), total)
    return cache_root

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
from pdd_agent.integrations.minio.index import find_sets_for_product_code, resolve_minio_set_prefix
from pdd_agent.skills.listing.catalog import (
    _parse_listing_target_product_selector,
    is_image_set_dir,
)
from pdd_agent.integrations.minio.client import get_minio_client
from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config, minio_cache_root, minio_configured

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


def _sets_for_product_inputs(
    product_inputs: list[str],
    config: MinioConfig | None = None,
) -> set[tuple[str, str]]:
    """从 selector（BD021/第一套图/BD021A）或裸编码解析需同步的套图，避免无谓全桶扫描。"""
    sets: set[tuple[str, str]] = set()
    lookup_codes: set[str] = set()

    for raw in product_inputs:
        selector = str(raw or "").strip()
        if not selector:
            continue
        parsed = _parse_listing_target_product_selector(selector)
        if parsed:
            family_code, image_set, _product_code = parsed
            sets.add((family_code, image_set))
            continue
        parts = [part.strip() for part in selector.split("/") if part.strip()]
        if len(parts) == 2 and is_image_set_dir(parts[1]):
            sets.add((parts[0], parts[1]))
            continue
        lookup_codes.add(selector.upper())

    if lookup_codes:
        for code in lookup_codes:
            for record in find_sets_for_product_code(code, config):
                sets.add((record.family_code, record.image_set))
        if not sets:
            for target in list_minio_listing_targets(config):
                target_codes = {str(item or "").strip().upper() for item in target.product_codes}
                if lookup_codes.intersection(target_codes):
                    sets.add((target.family_code, target.image_set))
    return sets


def _object_needs_download(client, bucket: str, key: str, dest_path: Path) -> bool:
    """本地已有且大小/时间与 MinIO 一致时跳过下载。"""
    if not dest_path.is_file():
        return True
    try:
        stat = client.stat_object(bucket, key)
        local_stat = dest_path.stat()
        if local_stat.st_size != stat.size:
            return True
        remote_ts = stat.last_modified.timestamp()
        if local_stat.st_mtime + 2 < remote_ts:
            return True
        return False
    except Exception:
        return True


def stage_minio_image_set(
    *,
    family_code: str,
    image_set: str,
    config: MinioConfig | None = None,
    cache_root: Path | None = None,
) -> tuple[int, int]:
    """下载某套图下全部兄弟商品文件夹到本地缓存，返回 (downloaded, skipped)。"""
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        return 0

    client = get_minio_client(cfg)
    dest_root = cache_root or minio_cache_root(cfg)
    grouped: dict[str, list[str]] = defaultdict(list)
    object_prefix = resolve_minio_set_prefix(family_code, image_set, cfg)
    list_prefixes: list[str] = []
    if object_prefix:
        list_prefixes = [object_prefix]
    else:
        set_suffix = f"{family_code}/{image_set}/"
        list_prefixes = [
            f"{scan_prefix}{set_suffix}" if scan_prefix else set_suffix
            for scan_prefix in _scan_prefixes(cfg)
        ]

    for list_prefix in list_prefixes:
        for obj in client.list_objects(cfg.bucket, prefix=list_prefix, recursive=True):
            key = obj.object_name
            resolved = _resolve_image_set_folder(key)
            if not resolved:
                continue
            resolved_family, resolved_set, product_folder = resolved
            if resolved_family != family_code or resolved_set != image_set:
                continue
            grouped[product_folder].append(key)

    written = 0
    skipped = 0
    for product_folder, keys in grouped.items():
        product_code = extract_product_code(product_folder)
        if not product_code:
            continue
        dest_dir = dest_root / family_code / image_set / product_code
        dest_dir.mkdir(parents=True, exist_ok=True)
        for key in keys:
            filename = key.split("/")[-1]
            dest_path = dest_dir / filename
            if _object_needs_download(client, cfg.bucket, key, dest_path):
                client.fget_object(cfg.bucket, key, str(dest_path))
                written += 1
            else:
                skipped += 1
    if written or skipped:
        logger.info(
            "minio staged set %s/%s -> downloaded=%s skipped=%s",
            family_code,
            image_set,
            written,
            skipped,
        )
    return written, skipped


def stage_minio_for_product_codes(product_codes: list[str], config: MinioConfig | None = None) -> Path:
    """按商品 selector/编码同步 MinIO 素材到本地缓存目录。"""
    cfg = config or load_minio_config()
    cache_root = minio_cache_root(cfg)
    cache_root.mkdir(parents=True, exist_ok=True)
    inputs = [str(code or "").strip() for code in product_codes if str(code or "").strip()]
    sets = _sets_for_product_inputs(inputs, cfg)
    downloaded = 0
    skipped = 0
    for family_code, image_set in sorted(sets):
        d, s = stage_minio_image_set(
            family_code=family_code,
            image_set=image_set,
            config=cfg,
            cache_root=cache_root,
        )
        downloaded += d
        skipped += s
    logger.info(
        "minio staged product_codes=%s sets=%s downloaded=%s skipped=%s",
        product_codes,
        len(sets),
        downloaded,
        skipped,
    )
    return cache_root

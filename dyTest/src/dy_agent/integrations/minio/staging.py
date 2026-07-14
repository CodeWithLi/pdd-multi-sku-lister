"""Sync MinIO objects to local cache for catalog parsing."""

from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path

from dy_agent.core.logging import get_logger
from dy_agent.integrations.minio.catalog import (
    _is_image_object_name,
    _scan_prefixes,
    extract_product_code,
    list_minio_listing_targets,
)
from dy_agent.integrations.minio.client import get_minio_client
from dy_agent.integrations.minio.config import MinioConfig, load_minio_config, minio_cache_root, minio_configured
from dy_agent.skills.listing.catalog import (
    IMAGE_EXTS,
    is_image_set_dir,
    parse_listing_target_product_selector,
    parse_listing_target_selector,
)

logger = get_logger(__name__)

_IGNORED_LOCAL_DIR_NAMES = frozenset({".alist", ".__jianying_export_temp_folder__"})


def _prune_stale_local_product_folders(
    *,
    dest_root: Path,
    family_code: str,
    image_set: str,
    remote_product_folders: set[str],
) -> int:
    if not remote_product_folders:
        return 0
    set_dir = dest_root / family_code / image_set
    if not set_dir.is_dir():
        return 0
    removed = 0
    for child in set_dir.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(".") or name in _IGNORED_LOCAL_DIR_NAMES:
            continue
        if name not in remote_product_folders:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
            logger.info("minio pruned stale local product folder %s/%s/%s", family_code, image_set, name)
    return removed


def _local_image_filenames(dest_dir: Path) -> set[str]:
    if not dest_dir.is_dir():
        return set()
    return {
        child.name
        for child in dest_dir.iterdir()
        if child.is_file() and child.suffix.lower() in IMAGE_EXTS
    }


def _format_sync_mismatch(
    *,
    family_code: str,
    image_set: str,
    product_code: str,
    remote_filenames: set[str],
    dest_dir: Path,
) -> str | None:
    local = _local_image_filenames(dest_dir)
    remote = set(remote_filenames)
    if local == remote:
        return None
    missing = sorted(remote - local)
    extra = sorted(local - remote)
    parts = [
        f"{family_code}/{image_set}/{product_code}: MinIO {len(remote)} 张，本地 {len(local)} 张",
    ]
    if missing:
        parts.append(f"缺 {', '.join(missing)}")
    if extra:
        parts.append(f"多 {', '.join(extra)}")
    return "；".join(parts)


def _prune_stale_local_image_files(dest_dir: Path, remote_filenames: set[str]) -> int:
    if not dest_dir.is_dir() or not remote_filenames:
        return 0
    removed = 0
    for child in dest_dir.iterdir():
        if not child.is_file():
            continue
        if child.suffix.lower() not in IMAGE_EXTS:
            continue
        if child.name in remote_filenames:
            continue
        child.unlink(missing_ok=True)
        removed += 1
        logger.info("minio pruned stale local file %s", child)
    return removed


def _resolve_image_set_folder(object_name: str) -> tuple[str, str, str] | None:
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
    sets: set[tuple[str, str]] = set()
    lookup_codes: set[str] = set()

    for raw in product_inputs:
        selector = str(raw or "").strip()
        if not selector:
            continue
        parsed = parse_listing_target_product_selector(selector)
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
        for target in list_minio_listing_targets(config):
            for pc in target.product_codes:
                pc_upper = str(pc or "").strip().upper()
                if pc_upper in lookup_codes:
                    sets.add((target.family_code, target.image_set))
    return sets


def _object_needs_download(client, bucket: str, key: str, dest_path: Path) -> bool:
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
) -> tuple[int, int, int, int, list[str]]:
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        return 0, 0, 0, 0, []

    client = get_minio_client(cfg)
    dest_root = cache_root or minio_cache_root(cfg)
    grouped: dict[str, list[str]] = defaultdict(list)
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
    pruned_files = 0
    mismatches: list[str] = []
    for product_folder, keys in grouped.items():
        product_code = extract_product_code(product_folder)
        if not product_code:
            continue
        dest_dir = dest_root / family_code / image_set / product_code
        dest_dir.mkdir(parents=True, exist_ok=True)
        remote_filenames = {key.split("/")[-1] for key in keys}
        for key in keys:
            filename = key.split("/")[-1]
            dest_path = dest_dir / filename
            if _object_needs_download(client, cfg.bucket, key, dest_path):
                client.fget_object(cfg.bucket, key, str(dest_path))
                written += 1
            else:
                skipped += 1
        pruned_files += _prune_stale_local_image_files(dest_dir, remote_filenames)
        mismatch = _format_sync_mismatch(
            family_code=family_code,
            image_set=image_set,
            product_code=product_code,
            remote_filenames=remote_filenames,
            dest_dir=dest_dir,
        )
        if mismatch:
            mismatches.append(mismatch)

    remote_folders = {folder_name for folder_name in grouped.keys() if extract_product_code(folder_name)}
    pruned_dirs = _prune_stale_local_product_folders(
        dest_root=dest_root,
        family_code=family_code,
        image_set=image_set,
        remote_product_folders=remote_folders,
    )
    if written or skipped or pruned_dirs or pruned_files or mismatches:
        logger.info(
            "minio staged set %s/%s -> downloaded=%s skipped=%s pruned_dirs=%s pruned_files=%s mismatches=%s",
            family_code,
            image_set,
            written,
            skipped,
            pruned_dirs,
            pruned_files,
            len(mismatches),
        )
    return written, skipped, pruned_dirs, pruned_files, mismatches


def stage_minio_for_product_codes(product_codes: list[str], config: MinioConfig | None = None) -> Path:
    cfg = config or load_minio_config()
    cache_root = minio_cache_root(cfg)
    cache_root.mkdir(parents=True, exist_ok=True)
    inputs = [str(code or "").strip() for code in product_codes if str(code or "").strip()]
    sets = _sets_for_product_inputs(inputs, cfg)
    if not sets:
        raise RuntimeError(f"MinIO 中未找到对应套图: {product_codes}")

    downloaded = 0
    skipped = 0
    pruned_dirs = 0
    pruned_files = 0
    mismatches: list[str] = []
    for family_code, image_set in sorted(sets):
        d, s, p, f, batch_mismatches = stage_minio_image_set(
            family_code=family_code,
            image_set=image_set,
            config=cfg,
            cache_root=cache_root,
        )
        downloaded += d
        skipped += s
        pruned_dirs += p
        pruned_files += f
        mismatches.extend(batch_mismatches)

    logger.info(
        "minio staged product_codes=%s sets=%s downloaded=%s skipped=%s pruned_dirs=%s pruned_files=%s mismatches=%s",
        product_codes,
        len(sets),
        downloaded,
        skipped,
        pruned_dirs,
        pruned_files,
        len(mismatches),
    )
    if mismatches:
        preview = "；".join(mismatches[:3])
        if len(mismatches) > 3:
            preview += f" 等 {len(mismatches)} 项"
        raise RuntimeError(f"MinIO 与本地缓存图片数量不一致：{preview}")
    return cache_root

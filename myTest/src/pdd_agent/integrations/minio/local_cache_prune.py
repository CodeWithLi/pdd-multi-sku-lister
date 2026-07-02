"""MinIO 与本地 minio_cache 套图目录一致性：清理远端已不存在的本地套图文件夹。"""

from __future__ import annotations

import shutil
from pathlib import Path

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.catalog import _scan_prefixes, resolve_listing_path_parts
from pdd_agent.integrations.minio.client import get_minio_client
from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config, minio_cache_root, minio_configured
from pdd_agent.skills.listing.catalog import is_image_set_dir

logger = get_logger(__name__)

_IGNORED_LOCAL_DIR_NAMES = frozenset({".alist", ".__jianying_export_temp_folder__"})


def family_list_prefixes(family_code: str, config: MinioConfig | None = None) -> list[str]:
    """列出 MinIO 中某款号可能的前缀（含类目）。"""
    cfg = config or load_minio_config()
    family = str(family_code or "").strip()
    if not family:
        return []

    prefixes: list[str] = []
    seen: set[str] = set()
    for category in cfg.categories or []:
        prefix = f"{str(category).strip()}/{family}/"
        if prefix not in seen:
            seen.add(prefix)
            prefixes.append(prefix)
    for scan_prefix in _scan_prefixes(cfg):
        prefix = f"{scan_prefix}{family}/" if scan_prefix else f"{family}/"
        if prefix not in seen:
            seen.add(prefix)
            prefixes.append(prefix)
    return prefixes


def list_remote_image_sets_for_family(
    family_code: str,
    *,
    config: MinioConfig | None = None,
) -> set[str]:
    """扫描 MinIO，返回某款号下仍含上架图片的套图名。"""
    cfg = config or load_minio_config()
    family = str(family_code or "").strip()
    if not family or not minio_configured(cfg):
        return set()

    client = get_minio_client(cfg)
    image_sets: set[str] = set()
    for list_prefix in family_list_prefixes(family, cfg):
        for obj in client.list_objects(cfg.bucket, prefix=list_prefix, recursive=True):
            key = str(obj.object_name or "")
            if not key:
                continue
            parsed = resolve_listing_path_parts(key.split("/"))
            if not parsed:
                continue
            fc, image_set, _product = parsed
            if fc == family:
                image_sets.add(image_set)
    return image_sets


def list_local_image_set_names(
    family_code: str,
    *,
    cache_root: Path | None = None,
    config: MinioConfig | None = None,
) -> set[str]:
    """列出本地缓存中某款号下的套图文件夹名。"""
    cfg = config or load_minio_config()
    root = cache_root or minio_cache_root(cfg)
    family_dir = root / str(family_code or "").strip()
    if not family_dir.is_dir():
        return set()
    return {
        child.name
        for child in family_dir.iterdir()
        if child.is_dir()
        and is_image_set_dir(child.name)
        and not child.name.startswith(".")
        and child.name not in _IGNORED_LOCAL_DIR_NAMES
    }


def prune_stale_local_image_sets_for_family(
    family_code: str,
    *,
    config: MinioConfig | None = None,
    cache_root: Path | None = None,
    remote_image_sets: set[str] | None = None,
) -> tuple[int, list[str]]:
    """删除本地款号下 MinIO 已不存在的套图文件夹。

    当 MinIO 端仍能扫到至少一套图时才执行清理，避免远端暂时不可达时误删本地缓存。
    返回 (删除套图数, 被删套图名列表)。
    """
    cfg = config or load_minio_config()
    root = cache_root or minio_cache_root(cfg)
    family = str(family_code or "").strip()
    if not family:
        return 0, []

    remote = (
        set(remote_image_sets)
        if remote_image_sets is not None
        else list_remote_image_sets_for_family(family, config=cfg)
    )
    if not remote:
        return 0, []

    local = list_local_image_set_names(family, cache_root=root, config=cfg)
    stale_names = sorted(local - remote)
    if not stale_names:
        return 0, []

    removed = 0
    removed_names: list[str] = []
    for image_set in stale_names:
        cache_dir = root / family / image_set
        if not cache_dir.is_dir():
            continue
        shutil.rmtree(cache_dir, ignore_errors=True)
        removed += 1
        removed_names.append(image_set)
        logger.info(
            "minio pruned stale local image set %s/%s (remote sets=%s)",
            family,
            image_set,
            sorted(remote),
        )
    return removed, removed_names


def prune_stale_local_image_sets_for_families(
    family_codes: list[str] | set[str],
    *,
    config: MinioConfig | None = None,
    cache_root: Path | None = None,
) -> tuple[int, dict[str, list[str]]]:
    """批量清理多个款号下已废弃的本地套图文件夹。"""
    cfg = config or load_minio_config()
    root = cache_root or minio_cache_root(cfg)
    families = [str(code or "").strip() for code in family_codes if str(code or "").strip()]
    unique_families = sorted(set(families))

    total_removed = 0
    removed_by_family: dict[str, list[str]] = {}
    for family in unique_families:
        removed, names = prune_stale_local_image_sets_for_family(
            family,
            config=cfg,
            cache_root=root,
        )
        if removed:
            total_removed += removed
            removed_by_family[family] = names
    return total_removed, removed_by_family

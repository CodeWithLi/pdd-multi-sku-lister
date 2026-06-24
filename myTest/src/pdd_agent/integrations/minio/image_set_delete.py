"""删除 MinIO / Alist 套图（双向联动：删存储 + 删 Alist 目录 + 清索引与本地缓存）。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Any

from minio.deleteobjects import DeleteObject

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.alist_client import (
    AlistAPIError,
    alist_configured,
    alist_virtual_path,
    delete_alist_path,
    login_alist,
)
from pdd_agent.integrations.minio.catalog import (
    clear_minio_listing_targets_cache,
    resolve_listing_path_parts,
)
from pdd_agent.integrations.minio.client import MinioAPIError, get_minio_client
from pdd_agent.integrations.minio.config import (
    MinioConfig,
    load_minio_config,
    minio_cache_root,
    minio_configured,
)
from pdd_agent.integrations.minio.index import (
    list_indexed_image_sets_for_family,
    list_indexed_products_for_set,
    load_set_index_record,
    remove_minio_set_record,
    remove_product_from_minio_set_record,
    resolve_minio_set_prefix,
)

logger = get_logger(__name__)


class ImageSetDeleteError(ValueError):
    pass


@dataclass(frozen=True)
class ImageSetDeleteResult:
    selector: str
    family_code: str
    image_set: str
    object_prefix: str
    deleted_object_count: int
    alist_deleted: bool
    alist_virtual_path: str
    local_cache_cleared: bool
    index_removed: bool
    cleaned_family_objects: int = 0
    family_folder_removed: bool = False
    remaining_object_count: int = 0
    remaining_image_sets: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        summary = f"已删除套图 {self.selector}：MinIO 共删除 {self.deleted_object_count} 个对象"
        if self.family_folder_removed:
            summary += f"，款号文件夹 {self.family_code} 已一并删除（MinIO + Alist）"
        elif self.alist_deleted:
            remaining = self.remaining_image_sets or []
            if remaining:
                summary += f"，款号文件夹 {self.family_code} 已保留（仍有套图：{'、'.join(remaining)}）"
            else:
                summary += "，Alist 套图目录已删除"
        if self.cleaned_family_objects and not self.family_folder_removed:
            summary += f"，并清理残留 {self.cleaned_family_objects} 个对象"
        if self.remaining_object_count:
            summary += f"（警告：仍有 {self.remaining_object_count} 个对象未删净，请刷新 MinIO 控制台）"
        return {
            "selector": self.selector,
            "family_code": self.family_code,
            "image_set": self.image_set,
            "object_prefix": self.object_prefix,
            "deleted_object_count": self.deleted_object_count,
            "alist_deleted": self.alist_deleted,
            "alist_virtual_path": self.alist_virtual_path,
            "local_cache_cleared": self.local_cache_cleared,
            "index_removed": self.index_removed,
            "cleaned_family_objects": self.cleaned_family_objects,
            "family_folder_removed": self.family_folder_removed,
            "remaining_object_count": self.remaining_object_count,
            "remaining_image_sets": list(self.remaining_image_sets or []),
            "summary": summary,
        }


@dataclass(frozen=True)
class ProductFolderDeleteResult:
    selector: str
    family_code: str
    image_set: str
    product_code: str
    object_prefix: str
    deleted_object_count: int
    alist_deleted: bool
    alist_virtual_path: str
    local_cache_cleared: bool
    index_updated: bool
    image_set_removed: bool = False
    family_folder_removed: bool = False
    cleaned_set_objects: int = 0
    cleaned_family_objects: int = 0
    remaining_object_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        summary = (
            f"已删除商品 {self.family_code}/{self.image_set}/{self.product_code}："
            f"MinIO 共删除 {self.deleted_object_count} 个对象"
        )
        if self.image_set_removed:
            summary += f"，套图 {self.image_set} 已空并已删除"
        if self.family_folder_removed:
            summary += f"，款号 {self.family_code} 已空并已删除"
        elif self.image_set_removed:
            summary += f"，款号 {self.family_code} 已保留"
        if self.remaining_object_count:
            summary += f"（警告：仍有 {self.remaining_object_count} 个对象未删净）"
        return {
            "selector": self.selector,
            "family_code": self.family_code,
            "image_set": self.image_set,
            "product_code": self.product_code,
            "object_prefix": self.object_prefix,
            "deleted_object_count": self.deleted_object_count,
            "alist_deleted": self.alist_deleted,
            "alist_virtual_path": self.alist_virtual_path,
            "local_cache_cleared": self.local_cache_cleared,
            "index_updated": self.index_updated,
            "image_set_removed": self.image_set_removed,
            "family_folder_removed": self.family_folder_removed,
            "cleaned_set_objects": self.cleaned_set_objects,
            "cleaned_family_objects": self.cleaned_family_objects,
            "remaining_object_count": self.remaining_object_count,
            "summary": summary,
        }


def _parse_selector(selector: str) -> tuple[str, str]:
    text = str(selector or "").strip().strip("/")
    if "/" not in text:
        raise ImageSetDeleteError("selector 格式应为 family_code/image_set，例如 BD021/第一套图")
    family_code, image_set = text.split("/", 1)
    family_code = family_code.strip()
    image_set = image_set.strip()
    if not family_code or not image_set:
        raise ImageSetDeleteError("selector 不能为空")
    return family_code, image_set


def _parse_product_selector(selector: str) -> tuple[str, str, str]:
    text = str(selector or "").strip().strip("/")
    parts = [part for part in text.split("/") if part]
    if len(parts) < 3:
        raise ImageSetDeleteError("selector 格式应为 family_code/image_set/product_code，例如 BD713/第一套图/BD713B")
    family_code = parts[0].strip()
    image_set = parts[1].strip()
    product_code = "/".join(parts[2:]).strip()
    if not family_code or not image_set or not product_code:
        raise ImageSetDeleteError("selector 不能为空")
    return family_code, image_set, product_code


def _candidate_prefixes(
    cfg: MinioConfig,
    *,
    family_code: str,
    image_set: str,
    object_prefix: str = "",
) -> list[str]:
    prefixes: list[str] = []
    seen: set[str] = set()

    def add(prefix: str) -> None:
        normalized = str(prefix or "").strip()
        if not normalized:
            return
        if not normalized.endswith("/"):
            normalized = f"{normalized}/"
        if normalized not in seen:
            seen.add(normalized)
            prefixes.append(normalized)

    if object_prefix:
        add(object_prefix)
    resolved = resolve_minio_set_prefix(family_code, image_set, cfg)
    if resolved:
        add(resolved)
    for category in cfg.categories:
        add(f"{category}/{family_code}/{image_set}")
    add(f"{family_code}/{image_set}")
    return prefixes


def _product_prefix_candidates(
    cfg: MinioConfig,
    *,
    family_code: str,
    image_set: str,
    product_code: str,
    object_prefix: str = "",
) -> list[str]:
    prefixes: list[str] = []
    seen: set[str] = set()
    product = str(product_code or "").strip()

    def add(prefix: str) -> None:
        normalized = str(prefix or "").strip()
        if not normalized:
            return
        if not normalized.endswith("/"):
            normalized = f"{normalized}/"
        if not _is_safe_product_delete_prefix(
            normalized,
            family_code=family_code,
            image_set=image_set,
            product_code=product,
        ):
            logger.warning(
                "skip unsafe product delete prefix=%s family=%s set=%s product=%s",
                normalized,
                family_code,
                image_set,
                product,
            )
            return
        if normalized not in seen:
            seen.add(normalized)
            prefixes.append(normalized)

    for set_prefix in _candidate_prefixes(
        cfg,
        family_code=family_code,
        image_set=image_set,
        object_prefix=object_prefix,
    ):
        add(f"{set_prefix.rstrip('/')}/{product}")
    return prefixes


def _set_prefix_from_product_prefix(
    product_prefix: str,
    *,
    family_code: str,
    image_set: str,
) -> str:
    text = str(product_prefix or "").strip().strip("/")
    parts = text.split("/")
    if len(parts) >= 4 and parts[-2] == image_set and parts[-3] == family_code:
        return f"{'/'.join(parts[:-1])}/"
    if len(parts) >= 3 and parts[-1] == image_set and parts[-2] == family_code:
        return f"{text}/"
    return ""


def _family_prefix_from_set_prefix(object_prefix: str, *, family_code: str = "") -> str:
    """从套图前缀推导款号前缀，如 笔袋/BD037/第一套图/ -> 笔袋/BD037/。"""
    text = str(object_prefix or "").strip().strip("/")
    if not text:
        return ""
    parts = text.split("/")
    family = str(family_code or "").strip()
    if len(parts) >= 3:
        candidate = f"{'/'.join(parts[:-1])}/"
        if family and parts[-2] != family:
            return ""
        return candidate
    if len(parts) == 2 and family and parts[-1] == family:
        return f"{text}/"
    return ""


def _is_safe_family_delete_prefix(prefix: str, family_code: str) -> bool:
    """款号级删除前缀必须至少为 category/family_code，禁止仅类目级（如 笔袋/）。"""
    text = str(prefix or "").strip().strip("/")
    family = str(family_code or "").strip()
    if not text or not family:
        return False
    parts = text.split("/")
    if len(parts) < 2:
        return False
    if parts[-1] != family:
        return False
    return True


def _is_safe_image_set_delete_prefix(prefix: str, family_code: str, image_set: str) -> bool:
    """套图级删除前缀必须至少为 category/family/image_set。"""
    text = str(prefix or "").strip().strip("/")
    family = str(family_code or "").strip()
    image_set_name = str(image_set or "").strip()
    if not text or not family or not image_set_name:
        return False
    parts = text.split("/")
    if len(parts) < 3:
        return False
    if parts[-1] != image_set_name or parts[-2] != family:
        return False
    return True


def _is_safe_product_delete_prefix(
    prefix: str,
    *,
    family_code: str,
    image_set: str,
    product_code: str,
) -> bool:
    """商品级删除前缀必须至少为 category/family/image_set/product。"""
    text = str(prefix or "").strip().strip("/")
    family = str(family_code or "").strip()
    image_set_name = str(image_set or "").strip()
    product = str(product_code or "").strip()
    if not text or not family or not image_set_name or not product:
        return False
    parts = text.split("/")
    if len(parts) < 4:
        return False
    if parts[-1] != product or parts[-2] != image_set_name or parts[-3] != family:
        return False
    return True


def _family_prefix_candidates(cfg: MinioConfig, family_code: str, *, hint_prefix: str = "") -> list[str]:
    """款号目录在 MinIO 中可能的前缀（含类目）。"""
    prefixes: list[str] = []
    seen: set[str] = set()
    family = str(family_code or "").strip()
    if not family:
        return prefixes

    def add(prefix: str) -> None:
        text = str(prefix or "").strip().strip("/")
        if not text:
            return
        normalized = f"{text}/"
        if not _is_safe_family_delete_prefix(normalized, family):
            logger.warning(
                "skip unsafe family delete prefix=%s family_code=%s",
                normalized,
                family,
            )
            return
        if normalized not in seen:
            seen.add(normalized)
            prefixes.append(normalized)

    hint = str(hint_prefix or "").strip().strip("/")
    if hint:
        parts = hint.split("/")
        if len(parts) >= 3:
            # 套图级 hint：笔袋/BD037/第一套图 -> 笔袋/BD037
            add("/".join(parts[:-1]))
        elif len(parts) >= 2 and parts[-1] == family:
            # 已是款号级 hint：笔袋/BD037
            add(hint)

    for category in cfg.categories:
        add(f"{category}/{family}")
    return prefixes


def _list_object_keys_for_prefixes(cfg: MinioConfig, prefixes: list[str]) -> tuple[list[str], str]:
    client = get_minio_client(cfg)
    keys: list[str] = []
    used_prefix = ""
    for prefix in prefixes:
        found: list[str] = []
        for obj in client.list_objects(cfg.bucket, prefix=prefix, recursive=True):
            if obj.object_name:
                found.append(obj.object_name)
        if found:
            keys.extend(found)
            if not used_prefix:
                used_prefix = prefix
    return sorted(set(keys)), used_prefix or (prefixes[0] if prefixes else "")


def _delete_minio_objects(cfg: MinioConfig, object_keys: list[str]) -> int:
    if not object_keys:
        return 0
    client = get_minio_client(cfg)
    deleted = 0
    batch_size = 100
    for start in range(0, len(object_keys), batch_size):
        batch = object_keys[start : start + batch_size]
        delete_targets = [DeleteObject(key) for key in batch]
        errors = list(client.remove_objects(cfg.bucket, delete_targets))
        if errors:
            messages = [f"{item.object_name}: {item.error}" for item in errors if item.error]
            raise ImageSetDeleteError("MinIO 删除失败: " + "; ".join(messages[:5]))
        deleted += len(batch)
    return deleted


def _image_sets_with_listing_in_minio(
    cfg: MinioConfig,
    family_prefix: str,
    family_code: str,
) -> set[str]:
    """MinIO 中某款号下仍含商品图片的套图名。"""
    prefix = str(family_prefix or "").strip()
    if not prefix.endswith("/"):
        prefix = f"{prefix}/"
    client = get_minio_client(cfg)
    image_sets: set[str] = set()
    for obj in client.list_objects(cfg.bucket, prefix=prefix, recursive=True):
        if not obj.object_name:
            continue
        parsed = resolve_listing_path_parts(obj.object_name.split("/"))
        if not parsed:
            continue
        fc, image_set, _product = parsed
        if fc == family_code:
            image_sets.add(image_set)
    return image_sets


def _collect_remaining_image_sets(
    cfg: MinioConfig,
    family_code: str,
    *,
    exclude_image_set: str,
    family_prefix_hint: str = "",
) -> set[str]:
    """删除当前套图后，款号下仍存在的其他套图（索引 + MinIO）。"""
    remaining = set(
        list_indexed_image_sets_for_family(cfg, family_code, exclude_image_set=exclude_image_set)
    )
    for family_prefix in _family_prefix_candidates(cfg, family_code, hint_prefix=family_prefix_hint):
        remaining.update(_image_sets_with_listing_in_minio(cfg, family_prefix, family_code))
    remaining.discard(exclude_image_set)
    return remaining


def should_remove_family_folder(
    cfg: MinioConfig,
    family_code: str,
    *,
    exclude_image_set: str,
    family_prefix_hint: str = "",
) -> bool:
    """是否应删除整个款号文件夹（仅剩当前套图或已无任何套图）。"""
    return not _collect_remaining_image_sets(
        cfg,
        family_code,
        exclude_image_set=exclude_image_set,
        family_prefix_hint=family_prefix_hint,
    )


def _delete_all_under_prefixes(
    cfg: MinioConfig,
    prefixes: list[str],
    *,
    family_code: str,
) -> int:
    safe_prefixes = [prefix for prefix in prefixes if _is_safe_family_delete_prefix(prefix, family_code)]
    if not safe_prefixes:
        logger.error(
            "refuse family cleanup: no safe prefixes family_code=%s candidates=%s",
            family_code,
            prefixes,
        )
        return 0
    keys, _ = _list_object_keys_for_prefixes(cfg, safe_prefixes)
    if not keys:
        return 0
    logger.info(
        "family cleanup family_code=%s prefixes=%s object_count=%s",
        family_code,
        safe_prefixes,
        len(keys),
    )
    return _delete_minio_objects(cfg, keys)


def _verify_prefixes_cleared(cfg: MinioConfig, prefixes: list[str]) -> int:
    remaining, _ = _list_object_keys_for_prefixes(cfg, prefixes)
    return len(remaining)


def _delete_alist_image_set_folder(
    cfg: MinioConfig,
    object_prefix: str,
    *,
    family_code: str = "",
    remove_family_folder: bool = False,
    token: str | None = None,
) -> tuple[bool, str, bool]:
    if not alist_configured(cfg):
        return False, "", False
    prefix = str(object_prefix or "").strip().strip("/")
    if not prefix:
        return False, "", False
    auth = token or login_alist(config=cfg)
    virtual_path = alist_virtual_path(prefix, config=cfg)
    delete_alist_path(virtual_path, token=auth, config=cfg)

    family_removed = False
    family_prefix = _family_prefix_from_set_prefix(prefix, family_code=family_code)
    if (
        remove_family_folder
        and family_prefix
        and _is_safe_family_delete_prefix(family_prefix, family_code)
    ):
        family_virtual = alist_virtual_path(family_prefix.rstrip("/"), config=cfg)
        delete_alist_path(family_virtual, token=auth, config=cfg)
        family_removed = True
    elif remove_family_folder and family_prefix:
        logger.error(
            "skip unsafe alist family delete family_code=%s family_prefix=%s",
            family_code,
            family_prefix,
        )
    return True, virtual_path, family_removed


def _clear_local_cache(
    cfg: MinioConfig,
    family_code: str,
    image_set: str,
    *,
    remove_family_folder: bool = False,
) -> bool:
    root = minio_cache_root(cfg)
    if remove_family_folder:
        cache_dir = root / family_code
    else:
        cache_dir = root / family_code / image_set
    if not cache_dir.exists():
        return False
    shutil.rmtree(cache_dir, ignore_errors=True)
    return True


def delete_minio_image_set(
    *,
    selector: str = "",
    family_code: str = "",
    image_set: str = "",
    config: MinioConfig | None = None,
    sync_alist: bool = True,
    clear_local_cache: bool = True,
) -> ImageSetDeleteResult:
    """删除一套图：MinIO 对象 + Alist 目录 + Redis 索引 + 本地缓存。"""
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        raise ImageSetDeleteError("MinIO 未配置")

    if selector:
        parsed_family, parsed_set = _parse_selector(selector)
        family_code = parsed_family
        image_set = parsed_set
    else:
        family_code = str(family_code or "").strip()
        image_set = str(image_set or "").strip()
        if not family_code or not image_set:
            raise ImageSetDeleteError("请提供 selector 或 family_code + image_set")

    selector_text = f"{family_code}/{image_set}"
    record = load_set_index_record(cfg, selector_text)
    object_prefix = record.object_prefix if record else ""
    set_prefixes = _candidate_prefixes(
        cfg,
        family_code=family_code,
        image_set=image_set,
        object_prefix=object_prefix,
    )
    object_keys, used_prefix = _list_object_keys_for_prefixes(cfg, set_prefixes)

    if not object_keys and not record:
        raise ImageSetDeleteError(f"未找到套图 {selector_text}（MinIO 与索引均无记录）")

    family_prefix = _family_prefix_from_set_prefix(used_prefix or object_prefix, family_code=family_code)
    remove_family = should_remove_family_folder(
        cfg,
        family_code,
        exclude_image_set=image_set,
        family_prefix_hint=family_prefix,
    )
    remaining_sets = sorted(
        _collect_remaining_image_sets(
            cfg,
            family_code,
            exclude_image_set=image_set,
            family_prefix_hint=family_prefix,
        )
    )

    deleted_count = _delete_minio_objects(cfg, object_keys)

    family_cleanup = 0
    if remove_family and family_prefix and _is_safe_family_delete_prefix(family_prefix, family_code):
        family_prefixes = _family_prefix_candidates(cfg, family_code, hint_prefix=family_prefix)
        family_cleanup = _delete_all_under_prefixes(cfg, family_prefixes, family_code=family_code)
    elif remove_family and family_prefix:
        logger.error(
            "skip unsafe family cleanup family_code=%s family_prefix=%s",
            family_code,
            family_prefix,
        )
        remove_family = False

    remaining = _verify_prefixes_cleared(cfg, set_prefixes)
    if remove_family and family_prefix:
        remaining += _verify_prefixes_cleared(
            cfg,
            _family_prefix_candidates(cfg, family_code, hint_prefix=family_prefix),
        )

    alist_deleted = False
    alist_virtual_path = ""
    family_folder_removed = False
    if sync_alist:
        try:
            alist_deleted, alist_virtual_path, family_folder_removed = _delete_alist_image_set_folder(
                cfg,
                used_prefix or object_prefix,
                family_code=family_code,
                remove_family_folder=remove_family,
            )
        except AlistAPIError as exc:
            logger.warning("alist delete skipped for %s: %s", selector_text, exc)

    product_codes = tuple(record.product_codes) if record else tuple()
    index_removed = remove_minio_set_record(cfg, selector_text, product_codes=product_codes)

    local_cleared = False
    if clear_local_cache:
        local_cleared = _clear_local_cache(
            cfg,
            family_code,
            image_set,
            remove_family_folder=remove_family,
        )

    clear_minio_listing_targets_cache()

    logger.info(
        "deleted image set %s objects=%s family_cleanup=%s remove_family=%s remaining_sets=%s alist=%s index=%s",
        selector_text,
        deleted_count,
        family_cleanup,
        remove_family,
        remaining_sets,
        alist_deleted,
        index_removed,
    )
    if remaining:
        raise ImageSetDeleteError(
            f"套图 {selector_text} 删除后 MinIO 仍有 {remaining} 个对象未清，请刷新控制台后重试"
        )

    return ImageSetDeleteResult(
        selector=selector_text,
        family_code=family_code,
        image_set=image_set,
        object_prefix=used_prefix or object_prefix,
        deleted_object_count=deleted_count + family_cleanup,
        alist_deleted=alist_deleted,
        alist_virtual_path=alist_virtual_path,
        local_cache_cleared=local_cleared,
        index_removed=index_removed,
        cleaned_family_objects=family_cleanup,
        family_folder_removed=family_folder_removed,
        remaining_object_count=remaining,
        remaining_image_sets=remaining_sets,
    )


def _products_with_listing_in_minio(
    cfg: MinioConfig,
    set_prefix: str,
    family_code: str,
    image_set: str,
) -> set[str]:
    """MinIO 中某套图下仍含商品图片的商品文件夹名。"""
    prefix = str(set_prefix or "").strip()
    if not prefix.endswith("/"):
        prefix = f"{prefix}/"
    client = get_minio_client(cfg)
    products: set[str] = set()
    for obj in client.list_objects(cfg.bucket, prefix=prefix, recursive=True):
        if not obj.object_name:
            continue
        parsed = resolve_listing_path_parts(obj.object_name.split("/"))
        if not parsed:
            continue
        fc, image_set_name, product_folder = parsed
        if fc == family_code and image_set_name == image_set:
            products.add(product_folder)
    return products


def _collect_remaining_products_in_set(
    cfg: MinioConfig,
    family_code: str,
    image_set: str,
    *,
    exclude_product: str,
    set_prefix_hint: str = "",
) -> set[str]:
    """删除当前商品后，套图下仍存在的其他商品（索引 + MinIO）。"""
    selector = f"{family_code}/{image_set}"
    remaining = set(list_indexed_products_for_set(cfg, selector, exclude_product=exclude_product))
    for set_prefix in _candidate_prefixes(
        cfg,
        family_code=family_code,
        image_set=image_set,
        object_prefix=set_prefix_hint,
    ):
        remaining.update(_products_with_listing_in_minio(cfg, set_prefix, family_code, image_set))
    remaining.discard(exclude_product)
    return remaining


def _delete_all_under_image_set_prefixes(
    cfg: MinioConfig,
    prefixes: list[str],
    *,
    family_code: str,
    image_set: str,
) -> int:
    safe_prefixes = [
        prefix
        for prefix in prefixes
        if _is_safe_image_set_delete_prefix(prefix, family_code, image_set)
    ]
    if not safe_prefixes:
        logger.error(
            "refuse image set cleanup: no safe prefixes family=%s set=%s candidates=%s",
            family_code,
            image_set,
            prefixes,
        )
        return 0
    keys, _ = _list_object_keys_for_prefixes(cfg, safe_prefixes)
    if not keys:
        return 0
    logger.info(
        "image set cleanup family=%s set=%s prefixes=%s object_count=%s",
        family_code,
        image_set,
        safe_prefixes,
        len(keys),
    )
    return _delete_minio_objects(cfg, keys)


def _clear_local_product_cache(
    cfg: MinioConfig,
    family_code: str,
    image_set: str,
    product_code: str,
    *,
    remove_image_set: bool = False,
    remove_family_folder: bool = False,
) -> bool:
    root = minio_cache_root(cfg)
    if remove_family_folder:
        cache_dir = root / family_code
    elif remove_image_set:
        cache_dir = root / family_code / image_set
    else:
        cache_dir = root / family_code / image_set / product_code
    if not cache_dir.exists():
        return False
    shutil.rmtree(cache_dir, ignore_errors=True)
    return True


def delete_minio_product_folder(
    *,
    selector: str = "",
    family_code: str = "",
    image_set: str = "",
    product_code: str = "",
    config: MinioConfig | None = None,
    sync_alist: bool = True,
    clear_local_cache: bool = True,
) -> ProductFolderDeleteResult:
    """删除套图下的单个商品文件夹；套图/款号空时才级联删除上级目录。"""
    cfg = config or load_minio_config()
    if not minio_configured(cfg):
        raise ImageSetDeleteError("MinIO 未配置")

    if selector:
        family_code, image_set, product_code = _parse_product_selector(selector)
    else:
        family_code = str(family_code or "").strip()
        image_set = str(image_set or "").strip()
        product_code = str(product_code or "").strip()
        if not family_code or not image_set or not product_code:
            raise ImageSetDeleteError("请提供 selector 或 family_code + image_set + product_code")

    selector_text = f"{family_code}/{image_set}/{product_code}"
    set_selector = f"{family_code}/{image_set}"
    record = load_set_index_record(cfg, set_selector)
    set_object_prefix = record.object_prefix if record else ""
    product_prefixes = _product_prefix_candidates(
        cfg,
        family_code=family_code,
        image_set=image_set,
        product_code=product_code,
        object_prefix=set_object_prefix,
    )
    object_keys, used_prefix = _list_object_keys_for_prefixes(cfg, product_prefixes)

    if not object_keys:
        if record and product_code in record.product_codes:
            index_updated = remove_product_from_minio_set_record(cfg, set_selector, product_code)
            clear_minio_listing_targets_cache()
            return ProductFolderDeleteResult(
                selector=selector_text,
                family_code=family_code,
                image_set=image_set,
                product_code=product_code,
                object_prefix=used_prefix,
                deleted_object_count=0,
                alist_deleted=False,
                alist_virtual_path="",
                local_cache_cleared=False,
                index_updated=index_updated,
            )
        raise ImageSetDeleteError(f"未找到商品 {selector_text}（MinIO 与索引均无记录）")

    set_prefix = _set_prefix_from_product_prefix(
        used_prefix or (product_prefixes[0] if product_prefixes else ""),
        family_code=family_code,
        image_set=image_set,
    ) or set_object_prefix

    remaining_products = _collect_remaining_products_in_set(
        cfg,
        family_code,
        image_set,
        exclude_product=product_code,
        set_prefix_hint=set_prefix or set_object_prefix,
    )
    remove_image_set = not remaining_products

    family_prefix = _family_prefix_from_set_prefix(set_prefix or set_object_prefix, family_code=family_code)
    remove_family = False
    remaining_sets: list[str] = []
    if remove_image_set:
        remove_family = should_remove_family_folder(
            cfg,
            family_code,
            exclude_image_set=image_set,
            family_prefix_hint=family_prefix,
        )
        remaining_sets = sorted(
            _collect_remaining_image_sets(
                cfg,
                family_code,
                exclude_image_set=image_set,
                family_prefix_hint=family_prefix,
            )
        )

    deleted_count = _delete_minio_objects(cfg, object_keys)

    set_cleanup = 0
    if remove_image_set:
        set_cleanup = _delete_all_under_image_set_prefixes(
            cfg,
            _candidate_prefixes(
                cfg,
                family_code=family_code,
                image_set=image_set,
                object_prefix=set_object_prefix,
            ),
            family_code=family_code,
            image_set=image_set,
        )

    family_cleanup = 0
    if remove_family and family_prefix and _is_safe_family_delete_prefix(family_prefix, family_code):
        family_cleanup = _delete_all_under_prefixes(
            cfg,
            _family_prefix_candidates(cfg, family_code, hint_prefix=family_prefix),
            family_code=family_code,
        )
    elif remove_family and family_prefix:
        logger.error(
            "skip unsafe family cleanup after product delete family=%s prefix=%s",
            family_code,
            family_prefix,
        )
        remove_family = False

    remaining = _verify_prefixes_cleared(cfg, product_prefixes)
    if remove_image_set:
        remaining += _verify_prefixes_cleared(
            cfg,
            _candidate_prefixes(
                cfg,
                family_code=family_code,
                image_set=image_set,
                object_prefix=set_object_prefix,
            ),
        )
    if remove_family and family_prefix:
        remaining += _verify_prefixes_cleared(
            cfg,
            _family_prefix_candidates(cfg, family_code, hint_prefix=family_prefix),
        )

    alist_deleted = False
    alist_path = ""
    if sync_alist and alist_configured(cfg):
        try:
            auth = login_alist(config=cfg)
            product_path = str(used_prefix or product_prefixes[0]).strip().strip("/")
            alist_path = alist_virtual_path(product_path, config=cfg)
            delete_alist_path(alist_path, token=auth, config=cfg)
            alist_deleted = True
            if remove_image_set:
                set_path = str(set_prefix or set_object_prefix).strip().strip("/")
                if set_path and _is_safe_image_set_delete_prefix(f"{set_path}/", family_code, image_set):
                    delete_alist_path(alist_virtual_path(set_path, config=cfg), token=auth, config=cfg)
            if remove_family and family_prefix and _is_safe_family_delete_prefix(family_prefix, family_code):
                delete_alist_path(
                    alist_virtual_path(family_prefix.rstrip("/"), config=cfg),
                    token=auth,
                    config=cfg,
                )
        except AlistAPIError as exc:
            logger.warning("alist delete skipped for %s: %s", selector_text, exc)

    if remove_image_set:
        index_updated = remove_minio_set_record(
            cfg,
            set_selector,
            product_codes=tuple(record.product_codes) if record else tuple(),
        )
    else:
        index_updated = remove_product_from_minio_set_record(cfg, set_selector, product_code)

    local_cleared = False
    if clear_local_cache:
        local_cleared = _clear_local_product_cache(
            cfg,
            family_code,
            image_set,
            product_code,
            remove_image_set=remove_image_set,
            remove_family_folder=remove_family,
        )

    clear_minio_listing_targets_cache()

    logger.info(
        "deleted product %s objects=%s remove_set=%s remove_family=%s remaining_products=%s",
        selector_text,
        deleted_count,
        remove_image_set,
        remove_family,
        sorted(remaining_products),
    )
    if remaining:
        raise ImageSetDeleteError(
            f"商品 {selector_text} 删除后 MinIO 仍有 {remaining} 个对象未清，请刷新控制台后重试"
        )

    return ProductFolderDeleteResult(
        selector=selector_text,
        family_code=family_code,
        image_set=image_set,
        product_code=product_code,
        object_prefix=used_prefix or (product_prefixes[0] if product_prefixes else ""),
        deleted_object_count=deleted_count + set_cleanup + family_cleanup,
        alist_deleted=alist_deleted,
        alist_virtual_path=alist_path,
        local_cache_cleared=local_cleared,
        index_updated=index_updated,
        image_set_removed=remove_image_set,
        family_folder_removed=remove_family,
        cleaned_set_objects=set_cleanup,
        cleaned_family_objects=family_cleanup,
        remaining_object_count=remaining,
    )

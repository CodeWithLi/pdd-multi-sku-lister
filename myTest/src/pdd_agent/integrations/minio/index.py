"""MinIO 套图索引：前端轮询时写入 Redis，后续按 object_prefix 精准 list。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config
from pdd_agent.integrations.redis.client import get_redis_client
from pdd_agent.integrations.redis.config import load_redis_config, redis_configured
from pdd_agent.skills.listing.catalog import ListingTargetOption, _image_set_sort_key

logger = get_logger(__name__)


@dataclass(frozen=True)
class MinioSetIndexRecord:
    selector: str
    family_code: str
    image_set: str
    object_prefix: str
    product_codes: tuple[str, ...]


def _bucket_namespace(cfg: MinioConfig) -> str:
    redis_cfg = load_redis_config()
    prefix = str(redis_cfg.key_prefix or "pdd").strip() or "pdd"
    bucket = str(cfg.bucket or "").strip()
    return f"{prefix}:minio:index:{bucket}"


def _meta_key(cfg: MinioConfig) -> str:
    return f"{_bucket_namespace(cfg)}:meta"


def _sets_key(cfg: MinioConfig) -> str:
    return f"{_bucket_namespace(cfg)}:sets"


def _codes_key(cfg: MinioConfig) -> str:
    return f"{_bucket_namespace(cfg)}:codes"


def object_prefix_from_object_key(object_name: str, family_code: str, image_set: str) -> str:
    marker = f"/{family_code}/{image_set}/"
    idx = object_name.find(marker)
    if idx < 0:
        return f"{family_code}/{image_set}/"
    return object_name[: idx + len(marker)]


def _record_to_dict(record: MinioSetIndexRecord) -> dict[str, Any]:
    return {
        "selector": record.selector,
        "family_code": record.family_code,
        "image_set": record.image_set,
        "object_prefix": record.object_prefix,
        "product_codes": list(record.product_codes),
    }


def _record_from_dict(data: dict[str, Any]) -> MinioSetIndexRecord | None:
    selector = str(data.get("selector") or "").strip()
    family_code = str(data.get("family_code") or "").strip()
    image_set = str(data.get("image_set") or "").strip()
    object_prefix = str(data.get("object_prefix") or "").strip()
    codes_raw = data.get("product_codes") or []
    product_codes = tuple(
        sorted({str(code or "").strip() for code in codes_raw if str(code or "").strip()})
    )
    if not selector or not family_code or not image_set:
        return None
    if not object_prefix:
        object_prefix = f"{family_code}/{image_set}/"
    return MinioSetIndexRecord(
        selector=selector,
        family_code=family_code,
        image_set=image_set,
        object_prefix=object_prefix,
        product_codes=product_codes,
    )


def save_minio_index(
    cfg: MinioConfig,
    records: list[MinioSetIndexRecord],
) -> bool:
    """全量写入套图索引到 Redis。"""
    if not redis_configured():
        return False
    client = get_redis_client()
    if client is None:
        return False

    sets_payload: dict[str, str] = {}
    codes_payload: dict[str, str] = {}
    for record in records:
        sets_payload[record.selector] = json.dumps(_record_to_dict(record), ensure_ascii=False)
        for code in record.product_codes:
            key = code.upper()
            selectors = set(json.loads(codes_payload.get(key, "[]")))
            selectors.add(record.selector)
            codes_payload[key] = json.dumps(sorted(selectors), ensure_ascii=False)

    meta = {
        "updated_at": time.time(),
        "bucket": cfg.bucket,
        "set_count": len(records),
    }
    pipe = client.pipeline()
    pipe.delete(_sets_key(cfg), _codes_key(cfg))
    if sets_payload:
        pipe.hset(_sets_key(cfg), mapping=sets_payload)
    if codes_payload:
        pipe.hset(_codes_key(cfg), mapping=codes_payload)
    pipe.set(_meta_key(cfg), json.dumps(meta, ensure_ascii=False))
    pipe.execute()
    logger.info(
        "minio index saved to redis bucket=%s sets=%s codes=%s",
        cfg.bucket,
        len(records),
        len(codes_payload),
    )
    return True


def upsert_minio_set_record(
    cfg: MinioConfig,
    *,
    family_code: str,
    image_set: str,
    product_code: str,
    object_prefix: str,
) -> MinioSetIndexRecord:
    """增量更新单个套图索引（RabbitMQ 上传事件用）。"""
    selector = f"{family_code}/{image_set}"
    code = str(product_code or "").strip()
    prefix = str(object_prefix or f"{family_code}/{image_set}/").strip()
    existing_codes: set[str] = set()

    if redis_configured():
        client = get_redis_client()
        if client is not None:
            raw = client.hget(_sets_key(cfg), selector)
            if raw:
                try:
                    data = json.loads(raw)
                except (TypeError, ValueError):
                    data = {}
                record = _record_from_dict(data if isinstance(data, dict) else {})
                if record is not None:
                    existing_codes.update(record.product_codes)
            if code:
                existing_codes.add(code)
            record = MinioSetIndexRecord(
                selector=selector,
                family_code=family_code,
                image_set=image_set,
                object_prefix=prefix,
                product_codes=tuple(sorted(existing_codes)),
            )
            pipe = client.pipeline()
            pipe.hset(_sets_key(cfg), selector, json.dumps(_record_to_dict(record), ensure_ascii=False))
            for pc in record.product_codes:
                key = pc.upper()
                selectors_raw = client.hget(_codes_key(cfg), key)
                selectors: set[str] = set()
                if selectors_raw:
                    try:
                        parsed = json.loads(selectors_raw)
                        if isinstance(parsed, list):
                            selectors.update(str(item) for item in parsed)
                    except (TypeError, ValueError):
                        pass
                selectors.add(selector)
                pipe.hset(_codes_key(cfg), key, json.dumps(sorted(selectors), ensure_ascii=False))
            meta = load_minio_index_meta(cfg) or {}
            meta.update(
                {
                    "updated_at": time.time(),
                    "bucket": cfg.bucket,
                    "set_count": client.hlen(_sets_key(cfg)),
                }
            )
            pipe.set(_meta_key(cfg), json.dumps(meta, ensure_ascii=False))
            pipe.execute()
            return record

    return MinioSetIndexRecord(
        selector=selector,
        family_code=family_code,
        image_set=image_set,
        object_prefix=prefix,
        product_codes=tuple(sorted(existing_codes | ({code} if code else set()))),
    )


def load_set_index_record(cfg: MinioConfig, selector: str) -> MinioSetIndexRecord | None:
    """读取单个套图索引（上传批次分类用）。"""
    if not redis_configured():
        return None
    client = get_redis_client()
    if client is None:
        return None
    raw = client.hget(_sets_key(cfg), str(selector or "").strip())
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return _record_from_dict(data if isinstance(data, dict) else {})


def list_indexed_image_sets_for_family(
    cfg: MinioConfig,
    family_code: str,
    *,
    exclude_image_set: str = "",
) -> set[str]:
    """从 Redis 索引列出某款号下的套图名（可选排除当前待删套图）。"""
    family = str(family_code or "").strip()
    if not family:
        return set()
    if not redis_configured():
        return set()
    client = get_redis_client()
    if client is None:
        return set()

    exclude = str(exclude_image_set or "").strip()
    image_sets: set[str] = set()
    raw_sets = client.hgetall(_sets_key(cfg))
    for blob in raw_sets.values():
        try:
            data = json.loads(blob)
        except (TypeError, ValueError):
            continue
        record = _record_from_dict(data if isinstance(data, dict) else {})
        if record is None or record.family_code != family:
            continue
        if exclude and record.image_set == exclude:
            continue
        image_sets.add(record.image_set)
    return image_sets


def load_minio_index_meta(cfg: MinioConfig) -> dict[str, Any] | None:
    if not redis_configured():
        return None
    client = get_redis_client()
    if client is None:
        return None
    raw = client.get(_meta_key(cfg))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_minio_index_fresh(cfg: MinioConfig, *, cache_seconds: int) -> bool:
    meta = load_minio_index_meta(cfg)
    if not meta:
        return False
    updated_at = float(meta.get("updated_at") or 0.0)
    if updated_at <= 0:
        return False
    return time.time() - updated_at < max(0, int(cache_seconds))


def load_listing_targets_from_redis(cfg: MinioConfig) -> list[ListingTargetOption] | None:
    """从 Redis 读取套图列表；索引不存在时返回 None。"""
    if not redis_configured():
        return None
    client = get_redis_client()
    if client is None:
        return None

    raw_sets = client.hgetall(_sets_key(cfg))
    if not raw_sets:
        return None

    targets: list[ListingTargetOption] = []
    for blob in raw_sets.values():
        try:
            data = json.loads(blob)
        except (TypeError, ValueError):
            continue
        record = _record_from_dict(data if isinstance(data, dict) else {})
        if record is None:
            continue
        targets.append(
            ListingTargetOption(
                selector=record.selector,
                family_code=record.family_code,
                image_set=record.image_set,
                product_codes=list(record.product_codes),
            )
        )
    targets.sort(key=lambda item: (item.family_code, _image_set_sort_key(item.image_set)))
    return targets


def resolve_minio_set_prefix(
    family_code: str,
    image_set: str,
    config: MinioConfig | None = None,
) -> str | None:
    """按套图 selector 从 Redis 取 MinIO object 前缀。"""
    cfg = config or load_minio_config()
    selector = f"{str(family_code or '').strip()}/{str(image_set or '').strip()}"
    if not selector or selector == "/":
        return None
    if not redis_configured():
        return None
    client = get_redis_client()
    if client is None:
        return None
    raw = client.hget(_sets_key(cfg), selector)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    record = _record_from_dict(data if isinstance(data, dict) else {})
    if record is None:
        return None
    return record.object_prefix or None


def find_sets_for_product_code(
    product_code: str,
    config: MinioConfig | None = None,
) -> list[MinioSetIndexRecord]:
    """按商品编码从 Redis 反查所属套图。"""
    code = str(product_code or "").strip().upper()
    if not code:
        return []
    cfg = config or load_minio_config()
    if not redis_configured():
        return []
    client = get_redis_client()
    if client is None:
        return []

    raw = client.hget(_codes_key(cfg), code)
    if not raw:
        return []
    try:
        selectors = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(selectors, list):
        return []

    records: list[MinioSetIndexRecord] = []
    for selector in selectors:
        blob = client.hget(_sets_key(cfg), str(selector))
        if not blob:
            continue
        try:
            data = json.loads(blob)
        except (TypeError, ValueError):
            continue
        record = _record_from_dict(data if isinstance(data, dict) else {})
        if record is not None:
            records.append(record)
    return records


def remove_minio_set_record(
    cfg: MinioConfig,
    selector: str,
    *,
    product_codes: tuple[str, ...] | None = None,
) -> bool:
    """从 Redis 索引移除单个套图记录。"""
    selector_text = str(selector or "").strip()
    if not selector_text:
        return False
    if not redis_configured():
        return False
    client = get_redis_client()
    if client is None:
        return False

    codes: set[str] = set(product_codes or ())
    if not codes:
        raw = client.hget(_sets_key(cfg), selector_text)
        if raw:
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                data = {}
            record = _record_from_dict(data if isinstance(data, dict) else {})
            if record is not None:
                codes.update(record.product_codes)

    pipe = client.pipeline()
    pipe.hdel(_sets_key(cfg), selector_text)
    for code in codes:
        key = str(code or "").strip().upper()
        if not key:
            continue
        selectors_raw = client.hget(_codes_key(cfg), key)
        if not selectors_raw:
            continue
        try:
            selectors = {str(item) for item in json.loads(selectors_raw)}
        except (TypeError, ValueError):
            selectors = set()
        selectors.discard(selector_text)
        if selectors:
            pipe.hset(_codes_key(cfg), key, json.dumps(sorted(selectors), ensure_ascii=False))
        else:
            pipe.hdel(_codes_key(cfg), key)

    meta = load_minio_index_meta(cfg) or {}
    pipe.execute()
    meta.update(
        {
            "updated_at": time.time(),
            "bucket": cfg.bucket,
            "set_count": client.hlen(_sets_key(cfg)),
        }
    )
    client.set(_meta_key(cfg), json.dumps(meta, ensure_ascii=False))
    return True


def list_indexed_products_for_set(
    cfg: MinioConfig,
    selector: str,
    *,
    exclude_product: str = "",
) -> set[str]:
    """从 Redis 索引读取套图下仍存在的商品文件夹名。"""
    record = load_set_index_record(cfg, selector)
    if record is None:
        return set()
    excluded = str(exclude_product or "").strip()
    products = set(record.product_codes)
    if excluded:
        products.discard(excluded)
    return products


def remove_product_from_minio_set_record(
    cfg: MinioConfig,
    selector: str,
    product_code: str,
) -> bool:
    """从 Redis 索引移除套图下的单个商品；若套图已空则移除整条套图记录。"""
    selector_text = str(selector or "").strip()
    product = str(product_code or "").strip()
    if not selector_text or not product:
        return False
    if not redis_configured():
        return False
    client = get_redis_client()
    if client is None:
        return False

    raw = client.hget(_sets_key(cfg), selector_text)
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return False
    record = _record_from_dict(data if isinstance(data, dict) else {})
    if record is None or product not in record.product_codes:
        return False

    remaining = [code for code in record.product_codes if code != product]
    if not remaining:
        return remove_minio_set_record(cfg, selector_text, product_codes=(product,))

    updated = MinioSetIndexRecord(
        selector=record.selector,
        family_code=record.family_code,
        image_set=record.image_set,
        object_prefix=record.object_prefix,
        product_codes=tuple(remaining),
    )
    pipe = client.pipeline()
    pipe.hset(_sets_key(cfg), selector_text, json.dumps(_record_to_dict(updated), ensure_ascii=False))
    key = product.upper()
    selectors_raw = client.hget(_codes_key(cfg), key)
    if selectors_raw:
        try:
            selectors = {str(item) for item in json.loads(selectors_raw)}
        except (TypeError, ValueError):
            selectors = set()
        selectors.discard(selector_text)
        if selectors:
            pipe.hset(_codes_key(cfg), key, json.dumps(sorted(selectors), ensure_ascii=False))
        else:
            pipe.hdel(_codes_key(cfg), key)
    meta = load_minio_index_meta(cfg) or {}
    pipe.execute()
    meta.update(
        {
            "updated_at": time.time(),
            "bucket": cfg.bucket,
            "set_count": client.hlen(_sets_key(cfg)),
        }
    )
    client.set(_meta_key(cfg), json.dumps(meta, ensure_ascii=False))
    return True


def clear_minio_redis_index(cfg: MinioConfig | None = None) -> None:
    cfg = cfg or load_minio_config()
    client = get_redis_client()
    if client is None:
        return
    client.delete(_meta_key(cfg), _sets_key(cfg), _codes_key(cfg))

"""MinIO 上传事件解析与索引增量更新。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote_plus

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.catalog import (
    resolve_listing_path_parts,
    clear_minio_listing_targets_cache,
    extract_product_code,
)
from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config
from pdd_agent.integrations.minio.index import (
    MinioSetIndexRecord,
    object_prefix_from_object_key,
    upsert_minio_set_record,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class MinioUploadEvent:
    object_key: str
    bucket: str = ""
    event_name: str = ""
    filename: str = ""

    @property
    def family_code(self) -> str:
        parsed = self._parsed()
        return parsed[0] if parsed else ""

    @property
    def image_set(self) -> str:
        parsed = self._parsed()
        return parsed[1] if parsed else ""

    @property
    def product_code(self) -> str:
        parsed = self._parsed()
        return parsed[2] if parsed else ""

    @property
    def selector(self) -> str:
        if self.family_code and self.image_set:
            return f"{self.family_code}/{self.image_set}"
        return ""

    def _parsed(self) -> tuple[str, str, str] | None:
        parts = resolve_listing_path_parts(self.object_key.split("/"))
        if not parts:
            return None
        family_code, image_set, product_folder = parts
        product_code = extract_product_code(product_folder)
        if not product_code:
            return None
        return family_code, image_set, product_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_key": self.object_key,
            "bucket": self.bucket,
            "event_name": self.event_name,
            "filename": self.filename or self.object_key.rsplit("/", 1)[-1],
            "family_code": self.family_code,
            "image_set": self.image_set,
            "product_code": self.product_code,
            "selector": self.selector,
        }


def _normalize_object_key(raw: str, *, bucket: str = "") -> str:
    key = unquote_plus(str(raw or "").strip().lstrip("/"))
    cfg = load_minio_config()
    for prefix in (str(bucket or "").strip(), str(cfg.bucket or "").strip(), "beilemei-images"):
        if prefix and key.startswith(f"{prefix}/"):
            return key[len(prefix) + 1 :]
    return key


def _keys_from_mapping(data: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for field in ("object_key", "key", "path", "object_name", "file_path", "filepath"):
        value = data.get(field)
        if value:
            keys.append(_normalize_object_key(str(value)))
    records = data.get("Records")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            s3 = record.get("s3")
            if isinstance(s3, dict):
                obj = s3.get("object")
                if isinstance(obj, dict) and obj.get("key"):
                    keys.append(_normalize_object_key(str(obj["key"])))
            for field in ("key", "object_key", "path"):
                if record.get(field):
                    keys.append(_normalize_object_key(str(record[field])))
    return keys


def parse_rabbitmq_upload_message(body: bytes | str) -> list[MinioUploadEvent]:
    """从 RabbitMQ 消息体解析出一个或多个 object key。"""
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body or "")
    text = text.strip()
    if not text:
        return []

    events: list[MinioUploadEvent] = []
    seen: set[str] = set()

    def _append(key: str, *, bucket: str = "", event_name: str = "") -> None:
        normalized = _normalize_object_key(key, bucket=bucket)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        events.append(
            MinioUploadEvent(
                object_key=normalized,
                bucket=bucket,
                event_name=event_name,
                filename=normalized.rsplit("/", 1)[-1],
            )
        )

    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        if "/" in text and not text.startswith("{"):
            _append(_normalize_object_key(text))
        return events

    if isinstance(payload, str):
        if "/" in payload:
            _append(_normalize_object_key(payload))
        return events

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, str) and "/" in item:
                _append(_normalize_object_key(item))
            elif isinstance(item, dict):
                bucket = str(item.get("bucket") or item.get("bucket_name") or "")
                event_name = str(item.get("event_name") or item.get("action") or item.get("event") or "")
                for key in _keys_from_mapping(item):
                    _append(key, bucket=bucket, event_name=event_name)
        return events

    if isinstance(payload, dict):
        bucket = str(payload.get("bucket") or payload.get("bucket_name") or "")
        event_name = str(payload.get("event_name") or payload.get("action") or payload.get("event") or "")
        for key in _keys_from_mapping(payload):
            _append(key, bucket=bucket, event_name=event_name)
        return events

    return events


def apply_minio_upload_event(
    event: MinioUploadEvent,
    *,
    config: MinioConfig | None = None,
) -> MinioSetIndexRecord | None:
    """将单次上传事件合并进 Redis 套图索引。"""
    parsed = event._parsed()
    if not parsed:
        logger.debug("minio upload ignored (unrecognized path): %s", event.object_key)
        return None

    family_code, image_set, product_code = parsed
    cfg = config or load_minio_config()
    object_prefix = object_prefix_from_object_key(event.object_key, family_code, image_set)
    record = upsert_minio_set_record(
        cfg,
        family_code=family_code,
        image_set=image_set,
        product_code=product_code,
        object_prefix=object_prefix,
    )
    clear_minio_listing_targets_cache()
    logger.info(
        "minio upload indexed selector=%s product=%s file=%s",
        record.selector,
        product_code,
        event.filename,
    )
    return record


def summarize_upload_events(events: list[MinioUploadEvent]) -> dict[str, Any]:
    """合并多条上传为一条推送摘要。"""
    selectors: dict[str, set[str]] = {}
    files: list[str] = []
    for event in events:
        if not event.selector:
            continue
        selectors.setdefault(event.selector, set()).add(event.product_code)
        if event.filename:
            files.append(event.filename)
    if not selectors:
        return {"kind": "minio_upload", "selectors": [], "product_codes": [], "files": files[:20]}

    flat_codes = sorted({code for codes in selectors.values() for code in codes if code})
    return {
        "kind": "minio_upload",
        "selectors": sorted(selectors.keys()),
        "product_codes": flat_codes,
        "files": files[:20],
        "detail": "，".join(
            f"{selector}（{', '.join(sorted(codes))}）" for selector, codes in sorted(selectors.items())
        ),
    }

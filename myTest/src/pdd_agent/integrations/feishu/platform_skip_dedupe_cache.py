"""飞书「平台不适用跳过」Redis 缓存：拼多多 + 商品编码（全店铺共用，永不过期）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.listing_feishu_catalog import codes_match, normalize_listing_code
from pdd_agent.integrations.feishu.listing_feishu_platform_guard import (
    PLATFORM_SKIP_REASON,
    extract_product_folder_name,
)
from pdd_agent.integrations.redis.client import get_redis_client
from pdd_agent.integrations.redis.config import RedisConfig, load_redis_config

logger = get_logger(__name__)

PDD_PLATFORM = "拼多多"
_ENTRY_SEP = "|"

_local_entries: set[str] = set()
_local_meta: dict[str, Any] = {}


@dataclass(frozen=True)
class PlatformSkipEntry:
    merchant_code: str
    report_platform: str

    def cache_key(self) -> str:
        return platform_skip_entry_key(
            platform=self.report_platform,
            merchant_code=self.merchant_code,
        )


def platform_skip_entry_key(*, platform: str, merchant_code: str) -> str:
    """Redis 成员键：拼多多|BD751A。"""
    p = str(platform or PDD_PLATFORM).strip() or PDD_PLATFORM
    code = normalize_listing_code(merchant_code)
    return f"{p}{_ENTRY_SEP}{code}"


def parse_platform_skip_entry_key(key: str) -> tuple[str, str]:
    """解析缓存键；兼容旧版 拼多多|店铺|编码 三段格式。"""
    text = str(key or "").strip()
    parts = [part.strip() for part in text.split(_ENTRY_SEP) if part.strip()]
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) >= 3:
        return parts[0], parts[-1]
    return "", ""


def _entries_key(redis_cfg: RedisConfig) -> str:
    prefix = str(redis_cfg.key_prefix or "pdd").strip() or "pdd"
    return f"{prefix}:platform_skip:entries"


def _meta_key(redis_cfg: RedisConfig) -> str:
    prefix = str(redis_cfg.key_prefix or "pdd").strip() or "pdd"
    return f"{prefix}:platform_skip:meta"


def _ensure_platform_skip_keys_persistent(client: Any, redis_cfg: RedisConfig) -> None:
    """平台跳过编码为长期缓存，显式清除 TTL（永不过期）。"""
    try:
        client.persist(_entries_key(redis_cfg))
        client.persist(_meta_key(redis_cfg))
    except Exception:
        logger.exception("persist platform skip redis keys failed")


def platform_skip_dedupe_enabled(cfg: Any | None = None) -> bool:
    from pdd_agent.integrations.feishu.config import load_feishu_config

    active = cfg or load_feishu_config()
    return bool(active.pipeline.platform_skip_dedupe_enabled)


def platform_skip_dedupe_sync_seconds(cfg: Any | None = None) -> int:
    from pdd_agent.integrations.feishu.config import load_feishu_config

    active = cfg or load_feishu_config()
    return max(60, int(active.pipeline.platform_skip_dedupe_sync_seconds or 300))


def _load_entries_from_redis() -> set[str]:
    redis_cfg = load_redis_config()
    client = get_redis_client()
    if client is None:
        return set(_local_entries)
    try:
        members = client.smembers(_entries_key(redis_cfg))
        return {str(item).strip() for item in members if str(item).strip()}
    except Exception:
        logger.exception("load platform skip entries from redis failed")
        return set(_local_entries)


def _save_entries_to_redis(entries: list[PlatformSkipEntry], meta: dict[str, Any]) -> bool:
    global _local_entries, _local_meta

    redis_cfg = load_redis_config()
    client = get_redis_client()
    keys = sorted({entry.cache_key() for entry in entries if entry.cache_key()})
    _local_entries = set(keys)
    _local_meta = dict(meta)

    if client is None:
        logger.warning(
            "platform skip dedupe: redis unavailable, using in-memory cache count=%s",
            len(keys),
        )
        return False

    try:
        pipe = client.pipeline()
        entries_key = _entries_key(redis_cfg)
        meta_key = _meta_key(redis_cfg)
        pipe.delete(entries_key)
        if keys:
            pipe.sadd(entries_key, *keys)
        pipe.set(meta_key, json.dumps(meta, ensure_ascii=False))
        pipe.execute()
        _ensure_platform_skip_keys_persistent(client, redis_cfg)
        return True
    except Exception:
        logger.exception("save platform skip entries to redis failed")
        return False


def sync_platform_skip_codes_from_feishu(*, config: Any | None = None, client: Any | None = None) -> dict[str, Any]:
    """从飞书失败日志表同步「平台不适用跳过」编码到 Redis。"""
    from pdd_agent.integrations.feishu.config import load_feishu_config
    from pdd_agent.integrations.feishu.pdd_failure_log_read import list_platform_skip_records

    cfg = config or load_feishu_config()
    started_at = datetime.now(timezone.utc)
    try:
        records = list_platform_skip_records(config=cfg, client=client)
        entries = [
            PlatformSkipEntry(
                merchant_code=item["merchant_code"],
                report_platform=item["report_platform"],
            )
            for item in records
        ]
        meta = {
            "updated_at": started_at.isoformat(),
            "entry_count": len(entries),
            "failure_reason": PLATFORM_SKIP_REASON,
            "report_platform": PDD_PLATFORM,
            "redis_saved": False,
            "source": "feishu",
        }
        meta["redis_saved"] = _save_entries_to_redis(entries, meta)
        logger.info(
            "platform skip dedupe synced entries=%s redis=%s",
            len(entries),
            meta["redis_saved"],
        )
        return {"ok": True, "records": records, "meta": meta}
    except Exception as exc:
        logger.exception("sync platform skip entries from feishu failed")
        return {"ok": False, "error": str(exc), "records": [], "meta": {}}


def get_platform_skip_dedupe_status(*, config: Any | None = None) -> dict[str, Any]:
    from pdd_agent.integrations.feishu.config import load_feishu_config

    cfg = config or load_feishu_config()
    redis_cfg = load_redis_config()
    client = get_redis_client()
    entries = _load_entries_from_redis()
    meta: dict[str, Any] = {}
    if client is not None:
        try:
            raw = client.get(_meta_key(redis_cfg))
            if raw:
                meta = json.loads(raw)
        except Exception:
            logger.exception("load platform skip dedupe meta failed")
    if not meta and _local_meta:
        meta = dict(_local_meta)
    return {
        "enabled": platform_skip_dedupe_enabled(cfg),
        "sync_seconds": platform_skip_dedupe_sync_seconds(cfg),
        "code_count": len(entries),
        "updated_at": str(meta.get("updated_at") or ""),
        "redis_available": client is not None,
        "failure_reason": PLATFORM_SKIP_REASON,
    }


def remember_platform_skip_merchant_code(
    code: str,
    *,
    platform: str = PDD_PLATFORM,
) -> None:
    """首次写入「平台不适用跳过」后立即记入缓存，避免多子店铺重复写飞书。"""
    entry = PlatformSkipEntry(
        merchant_code=str(code or "").strip(),
        report_platform=str(platform or PDD_PLATFORM).strip() or PDD_PLATFORM,
    )
    key = entry.cache_key()
    if not key:
        return

    global _local_entries
    _local_entries.add(key)

    redis_cfg = load_redis_config()
    client = get_redis_client()
    if client is None:
        return
    try:
        client.sadd(_entries_key(redis_cfg), key)
        _ensure_platform_skip_keys_persistent(client, redis_cfg)
    except Exception:
        logger.exception("remember platform skip merchant_code failed code=%s", code)


def is_platform_skip_merchant_code(
    code: str,
    *,
    platform: str = PDD_PLATFORM,
    config: Any | None = None,
    require_enabled: bool = True,
    **_kwargs: Any,
) -> bool:
    """拼多多 + 商品编码是否在跳过缓存中（全店铺共用）。"""
    if require_enabled and not platform_skip_dedupe_enabled(config):
        return False
    norm = normalize_listing_code(code)
    if not norm:
        return False
    target_platform = str(platform or PDD_PLATFORM).strip() or PDD_PLATFORM
    cached = _load_entries_from_redis()
    for stored_key in cached:
        stored_platform, stored_code = parse_platform_skip_entry_key(stored_key)
        if stored_platform != target_platform:
            continue
        if stored_code == norm or codes_match(norm, stored_code):
            return True
    return False


def filter_selectors_by_platform_skip_dedupe(
    selectors: list[str],
    *,
    platform: str = PDD_PLATFORM,
    config: Any | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """返回仍应上架的 selector 与应静默跳过的 selector（不写失败日志、不打开浏览器）。"""
    passed: list[str] = []
    skipped: list[dict[str, str]] = []
    for raw in selectors or []:
        selector = str(raw or "").strip()
        if not selector:
            continue
        folder = extract_product_folder_name(selector)
        if folder and is_platform_skip_merchant_code(folder, platform=platform, config=config):
            skipped.append(
                {
                    "selector": selector,
                    "merchant_code": folder,
                    "listing_label": listing_label_from_selector(selector),
                    "report_platform": str(platform or PDD_PLATFORM),
                }
            )
            continue
        passed.append(selector)
    return {
        "passed_selectors": passed,
        "skipped": skipped,
        "skipped_count": len(skipped),
    }


def listing_label_from_selector(selector: str) -> str:
    """与整合链路套图 label 一致：BD739/第一套图/BD739A -> BD739A/第一套图。"""
    from pdd_agent.skills.listing.catalog import _parse_listing_target_product_selector

    text = str(selector or "").strip()
    parsed = _parse_listing_target_product_selector(text)
    if parsed:
        _family, image_set, product_code = parsed
        return f"{product_code}/{image_set}" if image_set else product_code
    parts = [part.strip() for part in text.split("/") if part.strip()]
    if len(parts) >= 3:
        return f"{parts[-1]}/{parts[-2]}"
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    return text

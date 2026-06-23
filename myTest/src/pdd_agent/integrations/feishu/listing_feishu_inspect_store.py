"""整合链路飞书定价读取结果持久化（DB meta + Redis）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.listing_feishu_inspect import (
    _merchant_code_from_selector,
    inspect_listing_feishu_prices,
)

logger = get_logger(__name__)

META_INSPECT_KEY = "feishu_price_inspect"
META_INSPECT_AT_KEY = "feishu_price_inspect_at"
_REDIS_TTL_SECONDS = 60 * 60 * 24 * 30


def _redis_key(pipeline_id: str) -> str:
    from pdd_agent.integrations.redis.config import load_redis_config

    prefix = str(load_redis_config().key_prefix or "pdd").strip() or "pdd"
    return f"{prefix}:pipeline:feishu_inspect:{pipeline_id}"


def merchant_codes_for_pipeline(data: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for row in data.get("listing_unit_statuses") or []:
        label = str(row.get("listing_label") or "").strip()
        if label:
            code = _merchant_code_from_selector(label.split("/")[0])
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
    for sel in data.get("product_codes") or []:
        code = _merchant_code_from_selector(str(sel))
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def save_pipeline_feishu_inspect(pipeline_id: str, data: dict[str, Any]) -> dict[str, Any]:
    saved_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    payload = dict(data)
    payload["pipeline_id"] = pipeline_id
    payload["saved_at"] = saved_at

    from pdd_agent.db.repositories import update_integrated_pipeline

    update_integrated_pipeline(
        pipeline_id,
        meta_patch={
            META_INSPECT_KEY: payload,
            META_INSPECT_AT_KEY: saved_at,
        },
    )

    try:
        from pdd_agent.integrations.redis.client import get_redis_client

        client = get_redis_client()
        if client is not None:
            client.setex(
                _redis_key(pipeline_id),
                _REDIS_TTL_SECONDS,
                json.dumps(payload, ensure_ascii=False, default=str),
            )
    except Exception:
        logger.exception("save pipeline feishu inspect to redis failed pipeline_id=%s", pipeline_id)

    return payload


def load_pipeline_feishu_inspect(pipeline_id: str) -> dict[str, Any] | None:
    from pdd_agent.db.repositories import get_integrated_pipeline

    row = get_integrated_pipeline(pipeline_id)
    if row is not None:
        meta = row.meta if isinstance(row.meta, dict) else {}
        stored = meta.get(META_INSPECT_KEY)
        if isinstance(stored, dict) and stored:
            return stored

    try:
        from pdd_agent.integrations.redis.client import get_redis_client

        client = get_redis_client()
        if client is not None:
            raw = client.get(_redis_key(pipeline_id))
            if raw:
                return json.loads(raw)
    except Exception:
        logger.exception("load pipeline feishu inspect from redis failed pipeline_id=%s", pipeline_id)
    return None


def capture_and_save_pipeline_feishu_inspect(
    pipeline_id: str,
    codes: list[str],
    *,
    force_refresh: bool = True,
) -> dict[str, Any]:
    data = inspect_listing_feishu_prices(codes, force_refresh=force_refresh)
    return save_pipeline_feishu_inspect(pipeline_id, data)


def schedule_pipeline_feishu_inspect_capture(pipeline_id: str, codes: list[str]) -> None:
    """后台抓取飞书定价数据并写入链路记录（不阻塞上架）。"""
    import threading

    merchant_codes = list(
        dict.fromkeys(
            code
            for raw in codes
            if (code := _merchant_code_from_selector(raw))
        )
    )
    if not merchant_codes:
        return

    def _run() -> None:
        try:
            capture_and_save_pipeline_feishu_inspect(
                pipeline_id,
                merchant_codes,
                force_refresh=True,
            )
            logger.info(
                "pipeline feishu inspect saved pipeline_id=%s codes=%s",
                pipeline_id,
                len(merchant_codes),
            )
        except Exception:
            logger.exception("pipeline feishu inspect capture failed pipeline_id=%s", pipeline_id)

    threading.Thread(
        target=_run,
        name=f"feishu-inspect-{pipeline_id[:12]}",
        daemon=True,
    ).start()

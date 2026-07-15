"""拼多多组合装定价 — 按商品编码读取「商品定价」（配件/子商品价格）。"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import (
    find_table_id_by_name,
    list_all_records,
    resolve_table_field_name,
    search_records_by_field_values,
)
from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.integrations.feishu.pdd_price_compare_sync import _field_number, _field_text
from pdd_agent.skills.listing.pdd_product_catalog import _norm_code

logger = get_logger(__name__)

_CACHE: dict[str, Any] = {"loaded_at": 0.0, "entries": None}


def clear_pdd_bundle_pricing_cache() -> None:
    _CACHE["loaded_at"] = 0.0
    _CACHE["entries"] = None


def resolve_pdd_bundle_pricing_table_id(
    cfg: FeishuConfig,
    api: FeishuClient,
    *,
    save_table_id: bool = False,
) -> str:
    bundle_cfg = cfg.pdd_bundle_pricing
    table_id = str(bundle_cfg.table_id or "").strip()
    if table_id:
        return table_id
    app_token = str(cfg.bitable_app_token or "").strip()
    table_name = str(bundle_cfg.table_name or "").strip()
    if not app_token or not table_name:
        return ""
    found = find_table_id_by_name(api, app_token, table_name)
    if found and save_table_id:
        from pdd_agent.integrations.feishu.config import save_pdd_bundle_pricing_table_id_to_config

        save_pdd_bundle_pricing_table_id_to_config(found)
    return str(found or "").strip()


def load_pdd_bundle_pricing_map(
    *,
    codes: list[str] | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    force_refresh: bool = False,
) -> dict[str, float]:
    """读取拼多多组合装定价表：商品编码 -> 商品定价。"""
    cfg = config or load_feishu_config()
    bundle_cfg = cfg.pdd_bundle_pricing
    if not bundle_cfg.enabled:
        return {}

    normalized_codes = list(dict.fromkeys(_norm_code(c) for c in (codes or []) if _norm_code(c)))
    cache_seconds = int(bundle_cfg.cache_seconds or 0)
    use_full_cache = not normalized_codes
    if (
        not force_refresh
        and cache_seconds > 0
        and use_full_cache
        and isinstance(_CACHE.get("entries"), dict)
        and time.time() - float(_CACHE.get("loaded_at") or 0) < cache_seconds
    ):
        return dict(_CACHE["entries"])

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {}

    api = client or FeishuClient(cfg)
    try:
        table_id = resolve_pdd_bundle_pricing_table_id(cfg, api, save_table_id=True)
    except Exception:
        logger.exception("resolve pdd bundle pricing table failed")
        return {}
    if not table_id:
        logger.warning("pdd bundle pricing table not found name=%s", bundle_cfg.table_name)
        return {}

    names = bundle_cfg.field_names
    code_field = resolve_table_field_name(api, app_token, table_id, names.product_code)
    pricing_field = resolve_table_field_name(api, app_token, table_id, names.pricing)
    if not code_field or not pricing_field:
        logger.warning(
            "pdd bundle pricing fields missing code=%s pricing=%s",
            names.product_code,
            names.pricing,
        )
        return {}

    try:
        if normalized_codes:
            records = search_records_by_field_values(
                api,
                app_token,
                table_id,
                field_name=code_field,
                values=normalized_codes,
            )
        else:
            records = list_all_records(api, app_token, table_id)
    except Exception:
        logger.exception("load pdd bundle pricing rows failed")
        return {}

    out: dict[str, float] = {}
    for item in records:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        raw_code = _field_text(fields, code_field)
        code = _norm_code(raw_code)
        if not code:
            continue
        price = _field_number(fields, pricing_field)
        if price is None:
            continue
        out[code] = round(float(price), 2)

    if use_full_cache and cache_seconds > 0:
        _CACHE["entries"] = dict(out)
        _CACHE["loaded_at"] = time.time()

    logger.info(
        "loaded pdd bundle pricing map size=%s codes=%s",
        len(out),
        len(normalized_codes) if normalized_codes else "all",
    )
    return out

"""聚水潭 ERP 商品列表 — 按商品编码读取可用数（上架库存）。"""

from __future__ import annotations

import time
from dataclasses import replace
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
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry, _norm_code

logger = get_logger(__name__)

_CACHE: dict[str, Any] = {"loaded_at": 0.0, "inventory": None}


def clear_jushuitan_inventory_cache() -> None:
    _CACHE["loaded_at"] = 0.0
    _CACHE["inventory"] = None


def resolve_jushuitan_erp_table_id(
    cfg: FeishuConfig,
    api: FeishuClient,
    *,
    save_table_id: bool = False,
) -> str:
    inv_cfg = cfg.jushuitan_erp_inventory
    table_id = str(inv_cfg.table_id or "").strip()
    if table_id:
        return table_id
    app_token = str(cfg.bitable_app_token or "").strip()
    table_name = str(inv_cfg.table_name or "").strip()
    if not app_token or not table_name:
        return ""
    found = find_table_id_by_name(api, app_token, table_name)
    if found and save_table_id:
        from pdd_agent.integrations.feishu.config import save_jushuitan_erp_table_id_to_config

        save_jushuitan_erp_table_id_to_config(found)
    return str(found or "").strip()


def _parse_inventory_row(
    fields: dict[str, Any],
    *,
    code_field: str,
    qty_field: str,
) -> tuple[str, int] | None:
    raw_code = _field_text(fields, code_field)
    code = _norm_code(raw_code)
    if not code:
        return None
    qty = _field_number(fields, qty_field)
    return code, int(qty or 0)


def load_jushuitan_inventory_map(
    *,
    codes: list[str] | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    force_refresh: bool = False,
) -> dict[str, int]:
    """读取聚水潭 ERP 表：商品编码 -> 可用数。"""
    cfg = config or load_feishu_config()
    inv_cfg = cfg.jushuitan_erp_inventory
    if not inv_cfg.enabled:
        return {}

    normalized_codes = list(dict.fromkeys(_norm_code(c) for c in (codes or []) if _norm_code(c)))
    cache_seconds = int(inv_cfg.cache_seconds or 0)
    use_full_cache = not normalized_codes
    if (
        not force_refresh
        and cache_seconds > 0
        and use_full_cache
        and isinstance(_CACHE.get("inventory"), dict)
        and time.time() - float(_CACHE.get("loaded_at") or 0) < cache_seconds
    ):
        return dict(_CACHE["inventory"])

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {}

    api = client or FeishuClient(cfg)
    try:
        table_id = resolve_jushuitan_erp_table_id(cfg, api)
    except Exception:
        logger.exception("resolve jushuitan erp inventory table failed")
        return {}
    if not table_id:
        logger.warning("jushuitan erp inventory table not found name=%s", inv_cfg.table_name)
        return {}

    names = inv_cfg.field_names
    code_field = resolve_table_field_name(api, app_token, table_id, names.product_code)
    qty_field = resolve_table_field_name(api, app_token, table_id, names.available_qty)

    inventory: dict[str, int] = {}
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
        logger.exception("load jushuitan erp inventory failed table=%s", table_id)
        return {}

    for item in records:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        parsed = _parse_inventory_row(fields, code_field=code_field, qty_field=qty_field)
        if parsed:
            inventory[parsed[0]] = parsed[1]

    if use_full_cache and cache_seconds > 0:
        _CACHE["loaded_at"] = time.time()
        _CACHE["inventory"] = dict(inventory)

    logger.info(
        "jushuitan erp inventory loaded rows=%s codes=%s scoped=%s",
        len(records),
        len(inventory),
        bool(normalized_codes),
    )
    return inventory


def apply_jushuitan_inventory_to_catalog(
    catalog: dict[str, PddProductEntry],
    inventory_map: dict[str, int],
    *,
    enabled: bool = True,
) -> dict[str, PddProductEntry]:
    """用聚水潭可用数覆盖目录库存（定价/规格仍来自比价定价表）。"""
    if not enabled or not catalog:
        return catalog
    if not inventory_map:
        return catalog
    out: dict[str, PddProductEntry] = {}
    for code, entry in catalog.items():
        norm = _norm_code(code)
        inv = int(inventory_map.get(norm, 0) or 0)
        out[norm] = replace(entry, inventory=inv)
    return out


def enrich_catalog_with_jushuitan_inventory(
    catalog: dict[str, PddProductEntry],
    *,
    codes: list[str] | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    inventory_map: dict[str, int] | None = None,
) -> dict[str, PddProductEntry]:
    cfg = config or load_feishu_config()
    if not cfg.jushuitan_erp_inventory.enabled:
        return catalog
    inv_map = inventory_map
    if inv_map is None:
        try:
            lookup_codes = codes or list(catalog.keys())
            inv_map = load_jushuitan_inventory_map(codes=lookup_codes, config=cfg, client=client)
        except Exception:
            logger.exception("load jushuitan erp inventory for catalog enrich failed")
            return catalog
    return apply_jushuitan_inventory_to_catalog(catalog, inv_map, enabled=True)

"""PDD 商品下架表 — 负库存自动下架成功后写入飞书。"""

from __future__ import annotations

import threading
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.models import InventoryDelistRecordORM
from pdd_agent.integrations.feishu.bitable import (
    FIELD_DATETIME,
    FIELD_NUMBER,
    FIELD_SINGLE_SELECT,
    FIELD_TEXT,
    batch_create_records,
    ensure_fields,
    map_fields_to_table_names,
)
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    load_feishu_config,
    save_pdd_delist_table_id_to_config,
)
from pdd_agent.integrations.feishu.pdd_upload_sync import _resolve_or_create_pdd_table_id

logger = get_logger(__name__)

_STATUS_LABELS: dict[str, str] = {
    "completed": "已下架",
    "failed": "下架失败",
    "dry_run": "模拟下架",
    "skipped": "跳过",
    "not_found": "未找到",
}


def _date_to_ms(day: date) -> int:
    return int(datetime.combine(day, dt_time.min).timestamp() * 1000)


def _datetime_to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def map_delist_status_label(status: str, *, config: FeishuConfig | None = None) -> str:
    cfg = config or load_feishu_config()
    key = str(status or "").strip().lower()
    label = _STATUS_LABELS.get(key, "")
    if label and label in cfg.pdd_delist_log.status_options:
        return label
    if label:
        return label
    raw = str(status or "").strip()
    return raw or "未知"


def map_relist_label(is_relisted: bool, *, config: FeishuConfig | None = None) -> str:
    cfg = config or load_feishu_config()
    options = list(cfg.pdd_delist_log.relist_options or ["否", "是"])
    if not options:
        return "是" if is_relisted else "否"
    if is_relisted:
        return options[1] if len(options) > 1 else "是"
    return options[0]


def _field_defs_for_pdd_delist_log(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.pdd_delist_log.field_names
    delist_cfg = config.pdd_delist_log
    return [
        {
            "field_name": names.date,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False},
        },
        {
            "field_name": names.delisted_at,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm", "auto_fill": False},
        },
        {"field_name": names.account_name, "type": FIELD_TEXT},
        {"field_name": names.product_code, "type": FIELD_TEXT},
        {"field_name": names.available_qty, "type": FIELD_NUMBER},
        {
            "field_name": names.status,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in delist_cfg.status_options]},
        },
        {
            "field_name": names.is_relisted,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in delist_cfg.relist_options]},
        },
        {"field_name": names.record_id, "type": FIELD_TEXT},
    ]


def resolve_pdd_delist_log_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
    create_if_missing: bool = False,
) -> tuple[str, str]:
    delist_cfg = cfg.pdd_delist_log
    return _resolve_or_create_pdd_table_id(
        cfg,
        client,
        configured_id=delist_cfg.table_id,
        table_name=delist_cfg.table_name,
        save_table_id=save_table_id,
        save_fn=save_pdd_delist_table_id_to_config,
        create_if_missing=create_if_missing,
    )


def ensure_pdd_delist_log_table_ready(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    delist_cfg = cfg.pdd_delist_log
    if not delist_cfg.enabled:
        return {"skipped": True, "reason": "pdd_delist_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_delist_log_table_id(
        cfg, api, save_table_id=True, create_if_missing=False
    )
    if not table_id:
        return {
            "failed": True,
            "reason": "table_not_found",
            "message": f"未找到飞书表「{delist_cfg.table_name}」，请在多维表格中创建后重启服务",
        }

    ensure_fields(api, app_token, table_id, _field_defs_for_pdd_delist_log(cfg))
    logger.info("pdd delist log table ready table=%s(%s)", table_id, resolve_method)
    return {
        "ready": True,
        "table_id": table_id,
        "resolve_method": resolve_method,
    }


ensure_pdd_delist_log_tables_ready = ensure_pdd_delist_log_table_ready


def build_pdd_delist_log_row(
    record: InventoryDelistRecordORM | dict[str, Any],
    *,
    config: FeishuConfig | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    names = cfg.pdd_delist_log.field_names

    if isinstance(record, dict):
        data = record
        delisted_raw = data.get("delisted_at")
        if isinstance(delisted_raw, datetime):
            delisted_at = delisted_raw
        elif isinstance(delisted_raw, str) and delisted_raw.strip():
            delisted_at = datetime.fromisoformat(delisted_raw.replace("Z", "+00:00"))
        else:
            delisted_at = datetime.now()
        shop_name = str(data.get("shop_display_name") or "").strip()
        product_code = str(data.get("product_code") or "").strip()
        available_qty = data.get("erp_available_qty")
        delist_status = str(data.get("delist_status") or "").strip()
        is_relisted = bool(data.get("is_relisted"))
        record_id = str(data.get("record_id") or "").strip()
    else:
        delisted_at = record.delisted_at or datetime.now()
        shop_name = str(record.shop_display_name or "").strip()
        product_code = str(record.product_code or "").strip()
        available_qty = record.erp_available_qty
        delist_status = str(record.delist_status or "").strip()
        is_relisted = bool(record.is_relisted)
        record_id = str(record.record_id or "").strip()

    if not shop_name:
        from pdd_agent.core.account_display import resolve_account_display_name

        account_id = ""
        if isinstance(record, dict):
            account_id = str(record.get("account_id") or "").strip()
        else:
            account_id = str(record.account_id or "").strip()
        if account_id:
            shop_name = resolve_account_display_name(account_id)

    return {
        names.date: _date_to_ms(delisted_at.date()),
        names.delisted_at: _datetime_to_ms(delisted_at),
        names.account_name: shop_name,
        names.product_code: product_code,
        names.available_qty: available_qty,
        names.status: map_delist_status_label(delist_status, config=cfg),
        names.is_relisted: map_relist_label(is_relisted, config=cfg),
        names.record_id: record_id,
    }


def push_pdd_delist_log(
    record: InventoryDelistRecordORM | dict[str, Any],
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    delist_cfg = cfg.pdd_delist_log
    if not delist_cfg.enabled:
        return {"skipped": True, "reason": "pdd_delist_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    ready = ensure_pdd_delist_log_table_ready(cfg, api)
    if ready.get("failed") or ready.get("skipped"):
        return ready

    table_id = str(ready.get("table_id") or "")
    row = build_pdd_delist_log_row(record, config=cfg)
    mapped_row = map_fields_to_table_names(api, app_token, table_id, row)
    try:
        record_ids = batch_create_records(api, app_token, table_id, [mapped_row])
    except FeishuAPIError as exc:
        product_code = row.get(delist_cfg.field_names.product_code, "")
        logger.exception("push pdd delist log failed product=%s", product_code)
        return {"failed": True, "error": str(exc), "code": exc.code}

    logger.info(
        "pdd delist log pushed product=%s table=%s record_id=%s",
        row.get(delist_cfg.field_names.product_code, ""),
        table_id,
        record_ids[0] if record_ids else "",
    )
    return {
        "success": True,
        "created_count": len(record_ids),
        "record_ids": record_ids,
        "table_id": table_id,
    }


def update_pdd_delist_log_relist(
    record: InventoryDelistRecordORM | dict[str, Any],
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """按「记录ID」更新飞书 PDD商品下架表中的「是否重新上架」。"""
    from pdd_agent.integrations.feishu.bitable import batch_update_records, search_records_by_field

    cfg = config or load_feishu_config()
    delist_cfg = cfg.pdd_delist_log
    if not delist_cfg.enabled:
        return {"skipped": True, "reason": "pdd_delist_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    if isinstance(record, dict):
        record_id = str(record.get("record_id") or "").strip()
        is_relisted = bool(record.get("is_relisted"))
    else:
        record_id = str(record.record_id or "").strip()
        is_relisted = bool(record.is_relisted)

    if not record_id:
        return {"skipped": True, "reason": "missing_record_id"}

    api = client or FeishuClient(cfg)
    ready = ensure_pdd_delist_log_table_ready(cfg, api)
    if ready.get("failed") or ready.get("skipped"):
        return ready

    table_id = str(ready.get("table_id") or "")
    names = delist_cfg.field_names
    rows = search_records_by_field(
        api,
        app_token,
        table_id,
        field_name=names.record_id,
        value=record_id,
        page_size=5,
    )
    if not rows:
        logger.warning("pdd delist log relist update: feishu row not found record_id=%s", record_id)
        fallback = push_pdd_delist_log(record, config=cfg, client=api)
        fallback["fallback_create"] = True
        return fallback

    update_fields = {
        names.is_relisted: map_relist_label(is_relisted, config=cfg),
    }

    row_obj = record if not isinstance(record, dict) else None
    if row_obj is None and isinstance(record, dict):
        record_id_db = str(record.get("record_id") or "").strip()
        if record_id_db:
            from pdd_agent.db.repositories import get_inventory_delist_record

            row_obj = get_inventory_delist_record(record_id_db)
    if row_obj is None and record_id:
        from pdd_agent.db.repositories import get_inventory_delist_record

        row_obj = get_inventory_delist_record(record_id)

    product_code = ""
    merchant_code = ""
    if isinstance(record, dict):
        product_code = str(record.get("product_code") or "").strip()
        merchant_code = str(record.get("merchant_code") or "").strip()
    elif row_obj is not None:
        product_code = str(row_obj.product_code or "").strip()
        merchant_code = str(row_obj.merchant_code or "").strip()

    latest_qty = None
    if row_obj is not None and row_obj.erp_available_qty is not None:
        latest_qty = int(row_obj.erp_available_qty)
    elif product_code or merchant_code:
        from pdd_agent.integrations.feishu.jushuitan_erp_inventory import load_jushuitan_inventory_map
        from pdd_agent.inventory_delist.analysis import _inventory_for_product_code

        inventory_map = load_jushuitan_inventory_map(
            codes=[c for c in [product_code, merchant_code] if c],
            force_refresh=True,
        )
        latest_qty = _inventory_for_product_code(product_code, merchant_code, inventory_map)
    if latest_qty is not None:
        update_fields[names.available_qty] = int(latest_qty)
    mapped = map_fields_to_table_names(api, app_token, table_id, update_fields)
    updates = [{"record_id": str(row.get("record_id") or ""), "fields": mapped} for row in rows if row.get("record_id")]
    if not updates:
        return {"failed": True, "reason": "empty_feishu_updates"}

    try:
        updated_ids = batch_update_records(api, app_token, table_id, updates)
    except FeishuAPIError as exc:
        logger.exception("update pdd delist log relist failed record_id=%s", record_id)
        return {"failed": True, "error": str(exc), "code": exc.code}

    logger.info(
        "pdd delist log relist updated record_id=%s is_relisted=%s feishu_rows=%s",
        record_id,
        is_relisted,
        len(updated_ids),
    )
    return {
        "success": True,
        "updated_count": len(updated_ids),
        "record_ids": updated_ids,
        "table_id": table_id,
        "is_relisted": is_relisted,
    }


def _update_pdd_delist_log_relist_safe(record_id: str) -> None:
    from pdd_agent.db.repositories import get_inventory_delist_record

    rid = str(record_id or "").strip()
    if not rid:
        return
    row = get_inventory_delist_record(rid)
    if not row:
        logger.warning("pdd delist log relist sync skipped: db record missing record_id=%s", rid)
        return
    product_code = str(row.product_code or "").strip()
    try:
        result = update_pdd_delist_log_relist(row)
        if result.get("failed"):
            logger.error("[%s] feishu relist sync failed: %s", product_code, result)
        elif result.get("success"):
            label = "是" if row.is_relisted else "否"
            print(f"[{product_code}] 飞书下架表已更新「是否重新上架」={label}", flush=True)
    except Exception:
        logger.exception("update pdd delist log relist failed record_id=%s", rid)


def schedule_pdd_delist_log_relist_update(record_id: str) -> None:
    """恢复上架后异步同步飞书 PDD商品下架表。"""
    rid = str(record_id or "").strip()
    if not rid:
        return
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_delist_log.enabled:
        return

    thread = threading.Thread(
        target=_update_pdd_delist_log_relist_safe,
        args=(rid,),
        name="feishu-pdd-delist-relist",
        daemon=True,
    )
    thread.start()


def _push_pdd_delist_log_safe(record: InventoryDelistRecordORM | dict[str, Any]) -> None:
    product_code = ""
    if isinstance(record, dict):
        product_code = str(record.get("product_code") or "").strip()
    else:
        product_code = str(record.product_code or "").strip()
    try:
        result = push_pdd_delist_log(record)
        if result.get("failed"):
            logger.error("[%s] feishu delist log failed: %s", product_code, result)
        elif result.get("created_count"):
            print(f"[{product_code}] 飞书下架记录已写入", flush=True)
    except Exception:
        logger.exception("push pdd delist log failed product=%s", product_code)


def schedule_pdd_delist_log(record: InventoryDelistRecordORM | dict[str, Any]) -> None:
    """数据库下架记录写入完成后，异步同步到飞书 PDD商品下架表。"""
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_delist_log.enabled:
        return

    thread = threading.Thread(
        target=_push_pdd_delist_log_safe,
        args=(record,),
        name="feishu-pdd-delist-log",
        daemon=True,
    )
    thread.start()


__all__ = [
    "build_pdd_delist_log_row",
    "ensure_pdd_delist_log_table_ready",
    "ensure_pdd_delist_log_tables_ready",
    "map_delist_status_label",
    "map_relist_label",
    "push_pdd_delist_log",
    "schedule_pdd_delist_log",
    "schedule_pdd_delist_log_relist_update",
    "update_pdd_delist_log_relist",
]

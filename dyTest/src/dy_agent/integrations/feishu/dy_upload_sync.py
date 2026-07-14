"""DY发布日志表 — 上架成功写入飞书（对齐 PDD 发布日志流程）。"""

from __future__ import annotations

import threading
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

from dy_agent.core.logging import get_logger
from dy_agent.integrations.feishu.bitable import (
    FIELD_DATETIME,
    FIELD_NUMBER,
    FIELD_TEXT,
    FIELD_URL,
    batch_create_records,
    batch_update_records,
    ensure_fields,
    map_fields_to_table_names,
    search_records_by_field,
)
from dy_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from dy_agent.integrations.feishu.config import (
    FeishuConfig,
    load_feishu_config,
    save_dy_upload_table_id_to_config,
)
from dy_agent.integrations.feishu.table_resolve import resolve_feishu_table_id
from dy_agent.skills.listing.listing_published_product import parse_listed_at

logger = get_logger(__name__)

_WRONG_TABLE_ID_CODES = frozenset({1254004, 1254041})
_INVALID_FILTER_CODES = frozenset({1254018})


def _ms_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _date_to_ms(day: date) -> int:
    return _ms_timestamp(datetime.combine(day, dt_time.min))


def _resolve_account_display_name(account_id: str) -> str:
    try:
        from dy_agent.browser.shop_display_name import get_valid_shop_display_name

        name = get_valid_shop_display_name(account_id)
        if name:
            return name
    except Exception:
        pass
    return ""


def _dy_upload_dedupe_field(config: FeishuConfig) -> str:
    names = config.dy_upload_log.field_names
    return str(
        config.dy_upload_log.dedupe_field or names.link_product_id or "商品链接ID"
    ).strip()


def _field_defs_for_dy_upload_log(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.dy_upload_log.field_names
    datetime_prop = {"date_formatter": "yyyy/MM/dd HH:mm", "auto_fill": False}
    return [
        {
            "field_name": names.date,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False},
        },
        {"field_name": names.merchant_code, "type": FIELD_TEXT},
        {"field_name": names.combo_barcode, "type": FIELD_TEXT},
        {"field_name": names.link_product_id, "type": FIELD_TEXT},
        {"field_name": names.title, "type": FIELD_TEXT},
        {"field_name": names.price, "type": FIELD_NUMBER, "property": {"formatter": "0.00"}},
        {"field_name": names.link, "type": FIELD_URL},
        {"field_name": names.publish_start, "type": FIELD_DATETIME, "property": datetime_prop},
        {"field_name": names.publish_end, "type": FIELD_DATETIME, "property": datetime_prop},
        {
            "field_name": names.duration_seconds,
            "type": FIELD_NUMBER,
            "property": {"formatter": "0.00"},
        },
        {"field_name": names.account_name, "type": FIELD_TEXT},
    ]


def _ensure_dy_upload_table_fields(
    client: FeishuClient, config: FeishuConfig, app_token: str, table_id: str
) -> None:
    ensure_fields(client, app_token, table_id, _field_defs_for_dy_upload_log(config))


def resolve_dy_upload_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
) -> tuple[str, str]:
    dy_cfg = cfg.dy_upload_log
    return resolve_feishu_table_id(
        cfg,
        client,
        configured_id=dy_cfg.table_id,
        table_name=dy_cfg.table_name,
        save_table_id=save_table_id,
        save_fn=save_dy_upload_table_id_to_config,
        create_if_missing=False,
    )


def ensure_dy_upload_log_table_ready(
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    if not cfg.dy_upload_log.enabled:
        return {"ready": False, "reason": "dy_upload_log_disabled"}
    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"ready": False, "reason": "feishu_not_configured"}
    api = client or FeishuClient(cfg)
    table_id, method = resolve_dy_upload_table_id(cfg, api)
    if not table_id:
        return {
            "ready": False,
            "reason": "table_not_found",
            "table_name": cfg.dy_upload_log.table_name,
        }
    _ensure_dy_upload_table_fields(api, cfg, app_token, table_id)
    return {
        "ready": True,
        "table_id": table_id,
        "resolve_method": method,
        "table_name": cfg.dy_upload_log.table_name,
    }


def build_dy_upload_log_fields(
    *,
    config: FeishuConfig,
    title: str,
    merchant_code: str,
    product_id: str,
    product_link: str = "",
    account_name: str = "",
    combo_barcode: str = "",
    price: str | float = "",
    publish_start: datetime | None = None,
    publish_end: datetime | None = None,
    verified_at: datetime | None = None,
) -> dict[str, Any]:
    names = config.dy_upload_log.field_names
    end_at = publish_end or verified_at or datetime.now()
    start_at = publish_start or end_at
    duration = max(0.0, (end_at - start_at).total_seconds())
    link = str(product_link or "").strip()

    fields: dict[str, Any] = {
        names.date: _date_to_ms(end_at.date()),
        names.merchant_code: str(merchant_code or "").strip(),
        names.title: str(title or "").strip(),
        names.account_name: str(account_name or "").strip(),
        names.publish_start: _ms_timestamp(start_at),
        names.publish_end: _ms_timestamp(end_at),
        names.duration_seconds: round(duration, 2),
    }
    pid = str(product_id or "").strip()
    if pid and names.link_product_id:
        fields[names.link_product_id] = pid
    combo = str(combo_barcode or "").strip()
    if combo and names.combo_barcode:
        fields[names.combo_barcode] = combo
    price_text = str(price or "").strip()
    if price_text and names.price:
        try:
            fields[names.price] = float(price_text)
        except (TypeError, ValueError):
            fields[names.price] = price_text
    if link and names.link:
        fields[names.link] = {"link": link, "text": "查看商品"}
    return fields


def resolve_listing_display_price(unit_skus: list[Any] | None, item: dict[str, Any] | None = None) -> str:
    """取代表性售价写入飞书「价格」列：优先结果里已有价，否则取 SKU 最低价。"""
    item = item or {}
    for key in ("display_price", "price", "list_price"):
        raw = str(item.get(key) or "").strip()
        if raw:
            return raw.replace("¥", "").replace(",", "").strip()

    prices: list[float] = []
    for sku in unit_skus or []:
        raw = str(getattr(sku, "price", "") or "").strip()
        if not raw and isinstance(sku, dict):
            raw = str(sku.get("price") or "").strip()
        raw = raw.replace("¥", "").replace(",", "").strip()
        if not raw:
            continue
        try:
            prices.append(float(raw))
        except ValueError:
            continue
    if not prices:
        return ""
    return f"{min(prices):.2f}"


def _field_text_from_record(fields: dict[str, Any], field_name: str) -> str:
    if not field_name:
        return ""
    value = fields.get(field_name)
    if value is None:
        return ""
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("text") or first.get("name") or "").strip()
        return str(first).strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "").strip()
    return str(value).strip()


def _find_upload_log_record_for_row(
    existing_rows: list[dict[str, Any]],
    *,
    combo_field: str,
    combo_barcode: str,
) -> dict[str, Any] | None:
    target_combo = str(combo_barcode or "").strip().upper()
    for item in existing_rows:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        current = _field_text_from_record(fields, combo_field).upper()
        if target_combo:
            if current == target_combo:
                return item
        elif not current:
            return item
    return None


def _upsert_dy_upload_log_rows(
    *,
    cfg: FeishuConfig,
    api: FeishuClient,
    app_token: str,
    table_id: str,
    resolve_method: str,
    account_id: str,
    product_id: str,
    row_field_list: list[dict[str, Any]],
) -> dict[str, Any]:
    names = cfg.dy_upload_log.field_names
    combo_field = str(names.combo_barcode or "组合商品条码").strip()
    dedupe_field = _dy_upload_dedupe_field(cfg)

    try:
        existing_rows = search_records_by_field(
            api,
            app_token,
            table_id,
            field_name=dedupe_field,
            value=product_id,
        )
    except FeishuAPIError as exc:
        if exc.code in _INVALID_FILTER_CODES:
            existing_rows = []
        else:
            raise

    created_ids: list[str] = []
    updated_ids: list[str] = []
    stored_fields: list[dict[str, Any]] = []
    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []

    for raw_fields in row_field_list:
        mapped = map_fields_to_table_names(api, app_token, table_id, raw_fields)
        combo = _field_text_from_record(mapped, combo_field)
        match = _find_upload_log_record_for_row(
            existing_rows,
            combo_field=combo_field,
            combo_barcode=combo,
        )
        if match and match.get("record_id"):
            to_update.append({"record_id": str(match["record_id"]), "fields": mapped})
        else:
            to_create.append(mapped)
        stored_fields.append(mapped)

    if to_update:
        batch_update_records(api, app_token, table_id, to_update)
        updated_ids.extend(str(item["record_id"]) for item in to_update)
    if to_create:
        created_ids.extend(batch_create_records(api, app_token, table_id, to_create))

    logger.info(
        "[%s] feishu dy upload log upsert product_id=%s created=%s updated=%s table=%s(%s)",
        account_id or "-",
        product_id,
        len(created_ids),
        len(updated_ids),
        table_id,
        resolve_method,
    )
    return {
        "created": bool(created_ids),
        "updated": bool(updated_ids),
        "product_id": product_id,
        "table_id": table_id,
        "resolve_method": resolve_method,
        "record_ids": created_ids + updated_ids,
        "fields": stored_fields[0] if len(stored_fields) == 1 else stored_fields,
        "row_count": len(stored_fields),
    }


def push_dy_upload_log(
    *,
    account_id: str = "",
    listing_label: str = "",
    title: str,
    merchant_code: str,
    product_id: str,
    product_link: str = "",
    account_name: str = "",
    combo_barcode: str = "",
    price: str | float = "",
    publish_start: datetime | None = None,
    publish_end: datetime | None = None,
    verified_at: datetime | None = None,
    sku_rows: list[dict[str, Any]] | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    dy_cfg = cfg.dy_upload_log
    if not dy_cfg.enabled:
        return {"skipped": True, "reason": "dy_upload_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    product_id = str(product_id or "").strip()
    merchant_code = str(merchant_code or "").strip()
    if not product_id:
        return {"skipped": True, "reason": "missing_product_id"}

    verified = verified_at or datetime.now()
    effective_account_name = str(account_name or "").strip() or _resolve_account_display_name(account_id)
    effective_publish_end = publish_end or verified
    effective_publish_start = publish_start or effective_publish_end
    effective_link = str(product_link or "").strip()

    logger.info(
        "[%s] feishu dy upload log push start product_id=%s merchant_code=%s shop=%s",
        account_id or "-",
        product_id,
        merchant_code,
        effective_account_name or "-",
    )
    print(
        f"[{account_id or '-'}] [{listing_label or merchant_code}] "
        f"飞书 DY 发布日志写入准备 product_id={product_id} shop={effective_account_name or '-'}",
        flush=True,
    )

    from dy_agent.integrations.feishu.dy_upload_spec_log import (
        build_dy_upload_spec_log_rows,
        log_spec_sku_rows_enabled,
    )

    row_payloads: list[dict[str, Any]]
    if log_spec_sku_rows_enabled(cfg) and sku_rows:
        row_payloads = build_dy_upload_spec_log_rows(
            merchant_code=merchant_code,
            listing_title=title,
            sku_rows=sku_rows,
        )
    else:
        row_payloads = [
            {
                "merchant_code": merchant_code,
                "combo_barcode": combo_barcode,
                "title": title,
                "price": price,
                "row_kind": "summary",
            }
        ]

    row_field_list = [
        build_dy_upload_log_fields(
            config=cfg,
            title=str(row.get("title") or title),
            merchant_code=str(row.get("merchant_code") or merchant_code),
            product_id=product_id,
            product_link=effective_link,
            account_name=effective_account_name,
            combo_barcode=str(row.get("combo_barcode") or ""),
            price=str(row.get("price") or price or ""),
            publish_start=effective_publish_start,
            publish_end=effective_publish_end,
            verified_at=verified,
        )
        for row in row_payloads
    ]

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_dy_upload_table_id(cfg, api)
    if not table_id:
        msg = f"未找到飞书表「{dy_cfg.table_name}」，请检查 bitable_app_token 与表名"
        logger.error("feishu dy upload log failed: %s", msg)
        return {"failed": True, "reason": "table_not_found", "message": msg}

    _ensure_dy_upload_table_fields(api, cfg, app_token, table_id)

    try:
        return _upsert_dy_upload_log_rows(
            cfg=cfg,
            api=api,
            app_token=app_token,
            table_id=table_id,
            resolve_method=resolve_method,
            account_id=account_id,
            product_id=product_id,
            row_field_list=row_field_list,
        )
    except FeishuAPIError as exc:
        if exc.code not in _WRONG_TABLE_ID_CODES:
            raise
        table_id, resolve_method = resolve_dy_upload_table_id(cfg, api, save_table_id=True)
        if not table_id:
            raise
        _ensure_dy_upload_table_fields(api, cfg, app_token, table_id)
        return _upsert_dy_upload_log_rows(
            cfg=cfg,
            api=api,
            app_token=app_token,
            table_id=table_id,
            resolve_method=resolve_method,
            account_id=account_id,
            product_id=product_id,
            row_field_list=row_field_list,
        )


def _push_dy_upload_log_safe(**kwargs: Any) -> None:
    account_id = str(kwargs.get("account_id") or "")
    label = str(kwargs.get("listing_label") or kwargs.get("merchant_code") or "")
    try:
        result = push_dy_upload_log(**kwargs)
        row_count = result.get("row_count") or len(result.get("record_ids") or [])
        if result.get("created") or result.get("updated"):
            action = "写入" if result.get("created") and not result.get("updated") else "更新"
            if result.get("created") and result.get("updated"):
                action = "写入/更新"
            print(
                f"[{account_id}] [{label}] 飞书 DY 发布日志已{action} "
                f"rows={row_count} table={result.get('table_id')}",
                flush=True,
            )
        elif result.get("skipped"):
            print(
                f"[{account_id}] [{label}] 飞书 DY 发布日志跳过：{result.get('reason')}",
                flush=True,
            )
        elif result.get("failed"):
            print(
                f"[{account_id}] [{label}] 飞书 DY 发布日志失败：{result.get('message')}",
                flush=True,
            )
    except Exception as exc:
        logger.exception("feishu dy upload log failed account=%s label=%s", account_id, label)
        print(f"[{account_id}] [{label}] 飞书 DY 发布日志失败：{exc}", flush=True)


def schedule_dy_upload_log(**kwargs: Any) -> None:
    """写入 DY 发布成功日志。默认上架路径同步写入。"""
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.dy_upload_log.enabled:
        return

    if cfg.dy_upload_log.sync_on_listing:
        _push_dy_upload_log_safe(**kwargs)
        return

    thread = threading.Thread(
        target=_push_dy_upload_log_safe,
        kwargs=kwargs,
        name="feishu-dy-upload-log",
        daemon=True,
    )
    thread.start()


def schedule_feishu_dy_upload_log_from_listing(
    *,
    account_id: str,
    unit,
    item: dict[str, Any],
) -> None:
    """从单次上架成功结果调度写入 DY发布日志表。"""
    try:
        cfg = load_feishu_config()
        if not cfg.dy_upload_log.enabled:
            return

        product_id = str(item.get("dy_product_id") or "").strip()
        capture = item.get("goods_list_capture") if isinstance(item.get("goods_list_capture"), dict) else {}
        if not product_id:
            product_id = str(capture.get("dy_product_id") or "").strip()
        if not product_id:
            return

        submit_meta = item.get("publish_submit") if isinstance(item.get("publish_submit"), dict) else {}
        submitted_at = parse_listed_at(str(submit_meta.get("submitted_at") or ""))
        listed_at = parse_listed_at(str(item.get("listed_at") or "")) or datetime.now()
        title = str(item.get("title") or "").strip()
        merchant_code = str(item.get("merchant_code") or getattr(unit, "merchant_code", "") or "").strip()
        product_link = str(item.get("product_link") or capture.get("product_link") or "").strip()
        price = resolve_listing_display_price(getattr(unit, "skus", None), item)
        account_name = str(item.get("shop_display_name") or "").strip()
        if not account_name:
            account_name = _resolve_account_display_name(account_id)

        from dy_agent.integrations.feishu.dy_upload_spec_log import listing_unit_sku_metadata

        sku_rows = [listing_unit_sku_metadata(sku) for sku in (getattr(unit, "skus", None) or [])]

        schedule_dy_upload_log(
            account_id=account_id,
            listing_label=str(item.get("listing_label") or getattr(unit, "listing_label", "") or ""),
            title=title,
            merchant_code=merchant_code,
            product_id=product_id,
            product_link=product_link,
            account_name=account_name,
            price=price,
            sku_rows=sku_rows,
            publish_start=submitted_at,
            publish_end=listed_at,
            verified_at=listed_at,
        )
    except Exception as exc:
        label = getattr(unit, "listing_label", "") or item.get("listing_label") or ""
        print(f"[{account_id}] [{label}] 飞书 DY 发布日志调度失败：{exc}", flush=True)

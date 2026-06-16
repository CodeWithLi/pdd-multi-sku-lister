"""拼多多每日上架商品日志 — 表结构定义与从 DB 同步到飞书。"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import and_, func, or_, select

from pdd_agent.db.models import PublishedProductORM
from pdd_agent.db.session import is_database_available, session_scope
from pdd_agent.integrations.feishu.bitable import (
    FIELD_DATETIME,
    FIELD_NUMBER,
    FIELD_SINGLE_SELECT,
    FIELD_TEXT,
    FIELD_URL,
    batch_create_records,
    create_table,
    ensure_fields,
    find_table_id_by_name,
    search_records_by_field,
)
from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    FeishuFieldNames,
    load_feishu_config,
    save_table_id_to_config,
)

LISTING_LOG_TABLE_NAME = "拼多多每日上架商品日志"


def listing_log_field_defs(
    status_options: list[str],
    names: FeishuFieldNames | None = None,
) -> list[dict[str, Any]]:
    """与「技术支持」Base 中日志表对齐的列定义。"""
    n = names or FeishuFieldNames()
    return [
        {
            "field_name": n.date,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False},
        },
        {"field_name": n.link, "type": FIELD_URL},
        {"field_name": n.title, "type": FIELD_TEXT},
        {
            "field_name": n.price,
            "type": FIELD_NUMBER,
            "property": {"formatter": "0.00"},
        },
        {"field_name": n.merchant_code, "type": FIELD_TEXT},
        {
            "field_name": n.sku_count,
            "type": FIELD_NUMBER,
            "property": {"formatter": "0"},
        },
        {
            "field_name": n.published_at,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm", "auto_fill": False},
        },
        {
            "field_name": n.status,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": name} for name in status_options]},
        },
        {"field_name": n.mapping_id, "type": FIELD_TEXT},
        {"field_name": n.account_id, "type": FIELD_TEXT},
        {"field_name": n.pdd_product_id, "type": FIELD_TEXT},
        {"field_name": n.product_code, "type": FIELD_TEXT},
        {"field_name": n.image_set, "type": FIELD_TEXT},
    ]


def _standard_field_names(names: FeishuFieldNames) -> set[str]:
    return {
        names.date,
        names.link,
        names.title,
        names.price,
        names.merchant_code,
        names.sku_count,
        names.published_at,
        names.status,
    }


def _ms_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _date_to_ms(day: date) -> int:
    return _ms_timestamp(datetime.combine(day, time.min))


def _status_label(status: str) -> str:
    mapping = {"on_sale": "在售", "delisted": "已下架"}
    return mapping.get(str(status or "").strip(), "未知")


def _extract_title(spec_metadata: dict | None, listing_label: str) -> str:
    meta = spec_metadata or {}
    for key in ("title", "listing_title"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    return listing_label or str(meta.get("product_code") or "")


def _extract_price(spec_metadata: dict | None) -> float | None:
    meta = spec_metadata or {}
    skus = meta.get("skus")
    if not isinstance(skus, list) or not skus:
        return None
    first = skus[0] if isinstance(skus[0], dict) else {}
    for key in ("group_price", "single_price", "price"):
        raw = str(first.get(key) or "").strip()
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return None


def _extract_sku_count(spec_metadata: dict | None) -> int:
    meta = spec_metadata or {}
    skus = meta.get("skus")
    if isinstance(skus, list) and skus:
        return len(skus)
    style_codes = meta.get("style_codes")
    model_codes = meta.get("model_codes")
    if isinstance(style_codes, list) and isinstance(model_codes, list) and style_codes and model_codes:
        return len(style_codes) * len(model_codes)
    return 0


def _product_url(config: FeishuConfig, pdd_product_id: str, *, merchant: bool = False) -> str:
    template = config.merchant_goods_url_template if merchant else config.product_link_template
    return template.format(pdd_product_id=pdd_product_id)


def row_to_feishu_fields(
    row: PublishedProductORM,
    config: FeishuConfig,
    *,
    log_day: date,
    minimal_fields: bool = False,
) -> dict[str, Any]:
    published_at = row.published_at or row.created_at or datetime.now()
    title = _extract_title(row.spec_metadata, row.listing_label)
    price = _extract_price(row.spec_metadata)
    sku_count = _extract_sku_count(row.spec_metadata)
    pdd_id = str(row.pdd_product_id or "").strip()
    link = _product_url(config, pdd_id, merchant=True) if pdd_id else ""
    n = config.field_names

    fields: dict[str, Any] = {
        n.date: _date_to_ms(log_day),
        n.title: title,
        n.merchant_code: str(row.merchant_code or row.product_code or ""),
        n.sku_count: sku_count,
        n.published_at: _ms_timestamp(published_at),
        n.status: _status_label(row.status),
        n.mapping_id: row.mapping_id,
        n.account_id: row.account_id,
        n.pdd_product_id: pdd_id,
        n.product_code: row.product_code,
        n.image_set: row.image_set or "",
    }
    if link:
        fields[n.link] = {"link": link, "text": title or pdd_id}
    if price is not None:
        fields[n.price] = price

    if minimal_fields:
        allowed = _standard_field_names(n)
        return {key: value for key, value in fields.items() if key in allowed}
    return fields


def list_published_products_for_date(day: date) -> list[PublishedProductORM]:
    """读取指定日期上架成功的 published_products（按 published_at 自然日）。"""
    if not is_database_available():
        raise RuntimeError("需要 MySQL（DATABASE_URL）才能同步上架日志")

    start = datetime.combine(day, time.min)
    end = datetime.combine(day, time.max)

    with session_scope() as session:
        stmt = (
            select(PublishedProductORM)
            .where(
                PublishedProductORM.pdd_product_id != "",
                or_(
                    and_(
                        PublishedProductORM.published_at.is_not(None),
                        PublishedProductORM.published_at >= start,
                        PublishedProductORM.published_at <= end,
                    ),
                    and_(
                        PublishedProductORM.published_at.is_(None),
                        PublishedProductORM.created_at >= start,
                        PublishedProductORM.created_at <= end,
                    ),
                ),
            )
            .order_by(
                func.coalesce(PublishedProductORM.published_at, PublishedProductORM.created_at).asc(),
                PublishedProductORM.mapping_id.asc(),
            )
        )
        rows = list(session.scalars(stmt).all())
        for row in rows:
            session.expunge(row)
        return rows


def ensure_listing_log_table(
    config: FeishuConfig | None = None,
    *,
    client: FeishuClient | None = None,
    save_table_id: bool = True,
) -> str:
    """在指定 Base 中创建「拼多多每日上架商品日志」表及字段，返回 table_id。"""
    cfg = config or load_feishu_config()
    api = client or FeishuClient(cfg)
    app_token = cfg.bitable_app_token

    table_id = (cfg.table_id or "").strip()
    table_name = (cfg.table_name or LISTING_LOG_TABLE_NAME).strip()
    if not table_id:
        table_id = find_table_id_by_name(api, app_token, table_name)
    if not table_id:
        table_id = create_table(api, app_token, table_name)

    ensure_fields(
        api,
        app_token,
        table_id,
        listing_log_field_defs(cfg.status_options, cfg.field_names),
    )

    if save_table_id and table_id != (cfg.table_id or ""):
        save_table_id_to_config(table_id)

    return table_id


def sync_listing_log_for_date(
    day: date,
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    dry_run: bool = False,
    minimal_fields: bool = False,
) -> dict[str, Any]:
    """将指定日期的上架记录增量写入飞书（按映射ID去重）。"""
    cfg = config or load_feishu_config()
    api = client or FeishuClient(cfg)
    app_token = cfg.bitable_app_token
    table_id = (cfg.table_id or "").strip() or ensure_listing_log_table(cfg, client=api, save_table_id=True)

    rows = list_published_products_for_date(day)
    to_create: list[dict[str, Any]] = []
    skipped = 0

    for row in rows:
        mapping_id = row.mapping_id
        if cfg.dedupe_field:
            existing = search_records_by_field(
                api,
                app_token,
                table_id,
                field_name=cfg.dedupe_field,
                value=mapping_id,
            )
            if existing:
                skipped += 1
                continue
        to_create.append(
            row_to_feishu_fields(row, cfg, log_day=day, minimal_fields=minimal_fields)
        )

    if dry_run:
        return {
            "date": day.isoformat(),
            "table_id": table_id,
            "candidates": len(rows),
            "would_create": len(to_create),
            "skipped_existing": skipped,
            "preview": to_create[:3],
        }

    record_ids = batch_create_records(api, app_token, table_id, to_create)
    return {
        "date": day.isoformat(),
        "table_id": table_id,
        "candidates": len(rows),
        "created": len(record_ids),
        "skipped_existing": skipped,
        "record_ids": record_ids,
    }

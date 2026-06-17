"""投流昨日数据回写飞书 PDD营销日志表。"""

from __future__ import annotations

from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import (
    FIELD_DATETIME,
    FIELD_SINGLE_SELECT,
    FIELD_TEXT,
    batch_create_records,
    batch_update_records,
    ensure_fields,
    find_table_id_by_name,
    map_fields_to_table_names,
    resolve_table_field_name,
    search_records_by_field,
)
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    load_feishu_config,
    save_pdd_marketing_table_id_to_config,
)
from pdd_agent.integrations.feishu.pdd_upload_sync import _format_listing_error_reason

logger = get_logger(__name__)

_FEISHU_TRAFFIC_SUCCESS = "成功"
_FEISHU_TRAFFIC_FAILURE = "失败"


def _field_defs_for_pdd_marketing_log(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.pdd_marketing_log.field_names
    marketing_cfg = config.pdd_marketing_log
    return [
        {
            "field_name": names.date,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False},
        },
        {"field_name": names.account_id, "type": FIELD_TEXT},
        {"field_name": names.product_id, "type": FIELD_TEXT},
        {
            "field_name": names.traffic_result,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in marketing_cfg.traffic_result_options]},
        },
        {"field_name": names.traffic_error_reason, "type": FIELD_TEXT},
        {"field_name": names.traffic_spend, "type": FIELD_TEXT},
        {"field_name": names.traffic_amount, "type": FIELD_TEXT},
        {"field_name": names.traffic_roi, "type": FIELD_TEXT},
        {"field_name": names.traffic_total_cost, "type": FIELD_TEXT},
        {"field_name": names.traffic_net_amount, "type": FIELD_TEXT},
        {"field_name": names.traffic_net_roi, "type": FIELD_TEXT},
        {"field_name": names.traffic_net_orders, "type": FIELD_TEXT},
        {"field_name": names.traffic_cost_per_order, "type": FIELD_TEXT},
    ]


def resolve_pdd_marketing_log_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
) -> tuple[str, str]:
    """按表名优先解析 PDD营销日志表 table_id，返回 (table_id, method)。"""
    marketing_cfg = cfg.pdd_marketing_log
    app_token = str(cfg.bitable_app_token or "").strip()
    configured = str(marketing_cfg.table_id or "").strip()
    table_name = str(marketing_cfg.table_name or "").strip()

    if table_name:
        found = find_table_id_by_name(client, app_token, table_name)
        if found:
            if configured and configured != found:
                logger.warning(
                    "pdd marketing log table_id corrected by name: config=%s actual=%s name=%s",
                    configured,
                    found,
                    table_name,
                )
            if save_table_id and found != configured:
                try:
                    save_pdd_marketing_table_id_to_config(found)
                except Exception as exc:
                    logger.warning("save pdd marketing table_id failed: %s", exc)
            return found, "table_name"

    if configured:
        return configured, "config_table_id"
    return "", "missing"


def ensure_pdd_marketing_log_table_ready(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """启动或同步前确保 PDD营销日志表存在且字段齐全。"""
    cfg = config or load_feishu_config()
    marketing_cfg = cfg.pdd_marketing_log
    if not marketing_cfg.enabled:
        return {"skipped": True, "reason": "pdd_marketing_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_marketing_log_table_id(cfg, api)
    if not table_id:
        return {
            "failed": True,
            "reason": "table_not_found",
            "message": f"未找到飞书表「{marketing_cfg.table_name}」",
        }

    ensure_fields(api, app_token, table_id, _field_defs_for_pdd_marketing_log(cfg))
    logger.info(
        "pdd marketing log fields ensured table=%s method=%s",
        table_id,
        resolve_method,
    )
    print(
        f"[feishu] PDD营销日志表字段已就绪：{marketing_cfg.table_name} ({table_id})",
        flush=True,
    )
    return {"ready": True, "table_id": table_id, "resolve_method": resolve_method}


def _date_to_ms(day: date) -> int:
    return int(datetime.combine(day, dt_time.min).timestamp() * 1000)


def _build_traffic_metric_fields(
    *,
    config: FeishuConfig,
    report_date: date,
    account_id: str,
    product_id: str,
    metrics: dict[str, str],
) -> dict[str, Any]:
    names = config.pdd_marketing_log.field_names
    date_ms = _date_to_ms(report_date)
    fields: dict[str, Any] = {
        names.date: date_ms,
        names.account_id: str(account_id or "").strip(),
        names.product_id: str(product_id or "").strip(),
        names.traffic_result: _FEISHU_TRAFFIC_SUCCESS,
        names.traffic_error_reason: "",
    }
    mapping = {
        "spend": names.traffic_spend,
        "amount": names.traffic_amount,
        "roi": names.traffic_roi,
        "total_cost": names.traffic_total_cost,
        "net_amount": names.traffic_net_amount,
        "net_roi": names.traffic_net_roi,
        "net_orders": names.traffic_net_orders,
        "cost_per_order": names.traffic_cost_per_order,
    }
    for key, field_name in mapping.items():
        value = str(metrics.get(key) or "").strip()
        if value != "":
            fields[field_name] = value
    return fields


def _record_date_ms(fields: dict[str, Any], date_field_name: str) -> int | None:
    raw = fields.get(date_field_name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _find_record_by_date_and_product_id(
    client: FeishuClient,
    *,
    app_token: str,
    table_id: str,
    product_id_field: str,
    date_field: str,
    product_id: str,
    report_date: date,
    retries: int,
    interval_seconds: float,
) -> dict[str, Any] | None:
    import time

    product_id = str(product_id or "").strip()
    if not product_id:
        return None
    target_ms = _date_to_ms(report_date)
    resolved_date_field = resolve_table_field_name(client, app_token, table_id, date_field)
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        rows = search_records_by_field(
            client,
            app_token,
            table_id,
            field_name=product_id_field,
            value=product_id,
            page_size=50,
        )
        for row in rows:
            fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
            if _record_date_ms(fields, resolved_date_field) == target_ms:
                return row
        if attempt + 1 < attempts:
            time.sleep(max(0.5, float(interval_seconds)))
    return None


def sync_traffic_report_to_feishu(
    *,
    account_id: str = "",
    rows: list[dict[str, Any]],
    report_date: date | str,
    error: str = "",
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """将投流昨日数据按「日期 + 商品ID」写入飞书 PDD营销日志表（按天留存）。"""
    cfg = config or load_feishu_config()
    marketing_cfg = cfg.pdd_marketing_log
    if not marketing_cfg.enabled:
        return {"skipped": True, "reason": "pdd_marketing_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    if isinstance(report_date, str):
        try:
            parsed_date = date.fromisoformat(report_date[:10])
        except ValueError:
            parsed_date = date.today()
    else:
        parsed_date = report_date

    api = client or FeishuClient(cfg)
    ready = ensure_pdd_marketing_log_table_ready(cfg, api)
    if ready.get("failed") or ready.get("skipped"):
        return ready

    table_id = str(ready.get("table_id") or "").strip()
    resolve_method = str(ready.get("resolve_method") or "")
    if not table_id:
        table_id, resolve_method = resolve_pdd_marketing_log_table_id(cfg, api)
    if not table_id:
        return {
            "failed": True,
            "reason": "table_not_found",
            "message": f"未找到飞书表「{marketing_cfg.table_name}」",
        }

    product_id_field = str(marketing_cfg.field_names.product_id or "商品ID").strip()
    date_field = str(marketing_cfg.field_names.date or "日期").strip()
    updates: list[dict[str, Any]] = []
    creates: list[dict[str, Any]] = []

    if error and not rows:
        return {
            "failed": True,
            "reason": "scrape_failed",
            "message": error,
            "table_id": table_id,
        }

    for item in rows:
        if not isinstance(item, dict):
            continue
        product_id = str(item.get("product_id") or "").strip()
        if not product_id:
            continue
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        row = _find_record_by_date_and_product_id(
            api,
            app_token=app_token,
            table_id=table_id,
            product_id_field=product_id_field,
            date_field=date_field,
            product_id=product_id,
            report_date=parsed_date,
            retries=marketing_cfg.lookup_retries,
            interval_seconds=marketing_cfg.lookup_interval_seconds,
        )
        fields = _build_traffic_metric_fields(
            config=cfg,
            report_date=parsed_date,
            account_id=account_id,
            product_id=product_id,
            metrics=metrics,
        )
        fields = map_fields_to_table_names(api, app_token, table_id, fields)
        if not row:
            creates.append(fields)
            continue
        record_id = str(row.get("record_id") or "").strip()
        if not record_id:
            creates.append(fields)
            continue
        updates.append({"record_id": record_id, "fields": fields})

    updated_ids: list[str] = []
    created_ids: list[str] = []
    if creates:
        try:
            created_ids = batch_create_records(api, app_token, table_id, creates)
        except FeishuAPIError as exc:
            logger.exception("feishu traffic report create failed account=%s", account_id)
            return {
                "failed": True,
                "reason": "feishu_create_failed",
                "message": str(exc),
                "table_id": table_id,
            }
    if updates:
        try:
            batch_update_records(api, app_token, table_id, updates)
            updated_ids = [item["record_id"] for item in updates]
        except FeishuAPIError as exc:
            logger.exception("feishu traffic report sync failed account=%s", account_id)
            return {
                "failed": True,
                "reason": "feishu_update_failed",
                "message": str(exc),
                "table_id": table_id,
            }

    context = (
        f"account={account_id or '-'} report_date={parsed_date.isoformat()} "
        f"created={len(created_ids)} updated={len(updated_ids)} table={table_id}({resolve_method})"
    )
    logger.info("feishu traffic report sync %s", context)
    print(f"[{account_id or '-'}] 飞书投流数据回写（PDD营销日志表）：{context}", flush=True)

    return {
        "updated": bool(updated_ids),
        "created": bool(created_ids),
        "table_id": table_id,
        "resolve_method": resolve_method,
        "record_ids": updated_ids + created_ids,
        "created_record_ids": created_ids,
        "updated_record_ids": updated_ids,
        "report_date": parsed_date.isoformat(),
        "total_rows": len(rows),
    }


def format_traffic_scrape_failure_reason(result: dict[str, Any]) -> str:
    raw = str(result.get("message") or result.get("error") or "投流数据抓取失败").strip()
    return _format_listing_error_reason(raw)

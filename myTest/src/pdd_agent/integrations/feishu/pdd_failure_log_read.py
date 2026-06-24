"""读取拼多多/全平台发布失败日志表（含流程字段）。"""

from __future__ import annotations

from typing import Any

from pdd_agent.integrations.feishu.bitable import (
    FIELD_TEXT,
    find_table_id_by_name,
    list_all_records,
    list_fields,
)
from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.integrations.feishu.field_display import (
    format_datetime_ms,
    format_plain_text,
    format_user_names,
    resolve_process_status,
)
from pdd_agent.integrations.feishu.pdd_upload_sync import (
    _verify_pdd_table_id,
    resolve_pdd_upload_failure_table_id,
)

FAILURE_TABLE_NAME_ALIASES: tuple[str, ...] = (
    "全平台发布日志表（失效）",
    "全平台发布日志表（失败）",
    "淘宝+拼多多发布日志表（失败）",
)


def _resolve_failure_log_table(
    cfg: FeishuConfig,
    client: FeishuClient,
) -> tuple[str, str, str]:
    """返回 (table_id, table_name, resolve_method)。"""
    app_token = str(cfg.bitable_app_token or "").strip()
    pdd_cfg = cfg.pdd_upload_log
    configured_name = str(pdd_cfg.failure_table_name or "").strip()

    candidates: list[str] = []
    for name in (
        configured_name,
        *FAILURE_TABLE_NAME_ALIASES,
    ):
        if name and name not in candidates:
            candidates.append(name)

    for name in candidates:
        found = find_table_id_by_name(client, app_token, name)
        if found and _verify_pdd_table_id(client, app_token, found):
            return found, name, "table_name"

    table_id, method = resolve_pdd_upload_failure_table_id(
        cfg,
        client,
        save_table_id=False,
        create_if_missing=False,
    )
    if table_id:
        return table_id, configured_name or "", method

    return "", "", "missing"


def _resolve_mirror_field_name(
    configured: str,
    table_fields: list[dict[str, Any]],
) -> str:
    """解析处理状态镜像列名（配置名优先，否则按列名包含「处理状态镜像」匹配）。"""
    configured_name = str(configured or "").strip()
    field_names = [str(f.get("field_name") or "") for f in table_fields]
    if configured_name and configured_name in field_names:
        return configured_name

    for item in table_fields:
        name = str(item.get("field_name") or "")
        if "处理状态镜像" in name and int(item.get("type") or 0) == FIELD_TEXT:
            return name

    return configured_name or "处理状态镜像"


def list_pdd_failure_logs(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    api = client or FeishuClient(cfg)
    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token:
        return {"ok": False, "error": "未配置 bitable_app_token"}

    table_id, table_name, resolve_method = _resolve_failure_log_table(cfg, api)
    if not table_id:
        return {
            "ok": False,
            "error": "未找到发布失败日志表，请检查表名或 failure_table_id 配置",
            "table_name_candidates": list(FAILURE_TABLE_NAME_ALIASES),
        }

    names = cfg.pdd_upload_log.failure_field_names
    table_fields = list_fields(api, app_token, table_id)
    mirror_field_name = _resolve_mirror_field_name(
        str(names.process_status_mirror or ""),
        table_fields,
    )

    max_items = max(1, min(int(limit), 500))
    raw_records = list_all_records(api, app_token, table_id, page_size=max_items)
    if len(raw_records) > max_items:
        raw_records = raw_records[:max_items]

    items: list[dict[str, Any]] = []
    for record in raw_records:
        fields = record.get("fields") or {}
        mirror_text = format_plain_text(fields.get(mirror_field_name))
        processor_names = format_user_names(fields.get(names.processor))
        processed_at = format_datetime_ms(fields.get(names.processed_at))
        status = resolve_process_status(mirror_text=mirror_text)

        items.append(
            {
                "record_id": str(record.get("record_id") or record.get("id") or ""),
                "date": format_datetime_ms(fields.get(names.date)) or str(fields.get(names.date) or ""),
                "merchant_code": str(fields.get(names.merchant_code) or ""),
                "report_platform": str(fields.get(names.report_platform) or ""),
                "account_name": str(fields.get(names.account_name) or ""),
                "record_type": str(fields.get(names.record_type) or ""),
                "failure_reason": str(fields.get(names.failure_reason) or ""),
                "publish_start": format_datetime_ms(fields.get(names.publish_start)),
                "publish_end": format_datetime_ms(fields.get(names.publish_end)),
                "duration_seconds": str(fields.get(names.duration_seconds) or ""),
                "process_completed": {
                    "field_name": mirror_field_name,
                    "label": status["label"],
                    "source": status["source"],
                    "mirror_text": mirror_text,
                },
                "cycle_relist": format_plain_text(fields.get(names.cycle_relist)),
                "processor": processor_names,
                "processed_at": processed_at,
                "fields_raw": fields,
            }
        )

    mirror_readable = any(
        bool((row.get("process_completed") or {}).get("mirror_text"))
        for row in items
    )

    return {
        "ok": True,
        "app_token": app_token,
        "table_id": table_id,
        "table_name": table_name,
        "resolve_method": resolve_method,
        "mirror_field_name": mirror_field_name,
        "mirror_api_readable": mirror_readable,
        "total": len(items),
        "items": items,
        "field_meta": [
            {
                "field_id": str(f.get("field_id") or ""),
                "field_name": str(f.get("field_name") or ""),
                "type": int(f.get("type") or 0),
                "ui_type": str(f.get("ui_type") or ""),
            }
            for f in table_fields
        ],
    }

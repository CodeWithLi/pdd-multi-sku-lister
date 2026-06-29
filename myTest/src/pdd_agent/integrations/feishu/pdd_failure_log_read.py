"""读取拼多多/全平台发布失败日志表（含流程字段）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pdd_agent.integrations.feishu.bitable import (
    FIELD_SINGLE_SELECT,
    FIELD_TEXT,
    find_table_id_by_name,
    list_all_records,
    list_fields,
    resolve_table_field_name,
)
from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.integrations.feishu.field_display import (
    format_datetime_ms,
    format_plain_text,
    format_single_select,
    format_user_names,
    resolve_process_status,
)
from pdd_agent.integrations.feishu.listing_feishu_catalog import normalize_listing_code
from pdd_agent.integrations.feishu.listing_feishu_platform_guard import PLATFORM_SKIP_REASON
from pdd_agent.integrations.feishu.pdd_upload_sync import (
    _verify_pdd_table_id,
    resolve_pdd_upload_failure_table_id,
)

FAILURE_TABLE_NAME_ALIASES: tuple[str, ...] = (
    "全平台发布日志表（失效）",
    "全平台发布日志表（失败）",
    "淘宝+拼多多发布日志表（失败）",
)


def resolve_failure_log_table(
    cfg: FeishuConfig,
    client: FeishuClient,
) -> tuple[str, str, str]:
    """返回 (table_id, table_name, resolve_method)。"""
    return _resolve_failure_log_table(cfg, client)


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


def resolve_failure_log_account_field_name(
    configured: str,
    table_fields: list[dict[str, Any]],
) -> str:
    """解析失败日志「店铺」列名（配置名优先，兼容 店铺 / 店铺名称）。"""
    configured_name = str(configured or "").strip()
    field_names = [str(f.get("field_name") or "") for f in table_fields]
    if configured_name and configured_name in field_names:
        return configured_name

    for alias in ("店铺", "店铺名称"):
        if alias in field_names:
            return alias

    for item in table_fields:
        name = str(item.get("field_name") or "")
        field_type = int(item.get("type") or 0)
        if "店铺" in name and field_type in (1, 2, 15):
            return name

    return configured_name or "店铺"


def resolve_failure_log_account_id_field_name(
    configured: str,
    table_fields: list[dict[str, Any]],
) -> str:
    configured_name = str(configured or "").strip()
    if not configured_name:
        return ""
    field_names = [str(f.get("field_name") or "") for f in table_fields]
    if configured_name in field_names:
        return configured_name
    for alias in ("店铺ID", "account_id", "Account ID"):
        if alias in field_names:
            return alias
    return ""


def read_failure_log_account(
    fields: dict[str, Any],
    *,
    account_name_field: str,
    account_id_field: str = "",
) -> tuple[str, str]:
    """从飞书 fields 读取店铺展示名与 account_id（若有）。"""
    account_name = format_plain_text(fields.get(account_name_field))
    account_id = format_plain_text(fields.get(account_id_field)) if account_id_field else ""
    return account_name, account_id


def resolve_cycle_relist_field_name(
    configured: str,
    table_fields: list[dict[str, Any]],
) -> str:
    """解析「是否循环上架」列名（支持单选/文本，按列名包含「循环上架」匹配）。"""
    configured_name = str(configured or "").strip()
    field_names = [str(f.get("field_name") or "") for f in table_fields]
    if configured_name and configured_name in field_names:
        return configured_name

    for alias in ("是否已循环上架", "是否循环上架"):
        if alias in field_names:
            return alias

    for item in table_fields:
        name = str(item.get("field_name") or "")
        field_type = int(item.get("type") or 0)
        if "循环上架" not in name:
            continue
        if field_type in (FIELD_SINGLE_SELECT, FIELD_TEXT):
            return name

    return configured_name or "是否已循环上架"


def _resolve_cycle_relist_field_name(
    configured: str,
    table_fields: list[dict[str, Any]],
) -> str:
    return resolve_cycle_relist_field_name(configured, table_fields)


@dataclass(frozen=True)
class FailureLogTableContext:
    app_token: str
    table_id: str
    table_name: str
    resolve_method: str
    mirror_field_name: str
    cycle_relist_field_name: str
    account_name_field: str
    account_id_field: str
    failure_reason_field: str
    names: Any


def resolve_failure_log_table_context(
    cfg: FeishuConfig,
    api: FeishuClient,
) -> FailureLogTableContext | dict[str, Any]:
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
    cycle_relist_field_name = _resolve_cycle_relist_field_name(
        str(names.cycle_relist or ""),
        table_fields,
    )
    account_name_field = resolve_failure_log_account_field_name(
        str(names.account_name or ""),
        table_fields,
    )
    account_id_field = resolve_failure_log_account_id_field_name(
        str(getattr(names, "account_id", "") or ""),
        table_fields,
    )
    failure_reason_field = resolve_table_field_name(
        api,
        app_token,
        table_id,
        str(names.failure_reason or "失败原因"),
    )
    return FailureLogTableContext(
        app_token=app_token,
        table_id=table_id,
        table_name=table_name,
        resolve_method=resolve_method,
        mirror_field_name=mirror_field_name,
        cycle_relist_field_name=cycle_relist_field_name,
        account_name_field=account_name_field,
        account_id_field=account_id_field,
        failure_reason_field=failure_reason_field,
        names=names,
    )


def build_cycle_relist_empty_condition(
    api: FeishuClient,
    ctx: FailureLogTableContext,
) -> dict[str, Any]:
    """是否已循环上架=未选：勾选框用 is false，单选/文本用 isEmpty。"""
    from pdd_agent.integrations.feishu.bitable import get_table_field_meta
    from pdd_agent.integrations.feishu.field_display import is_checkbox_like_cycle_relist_field

    field_name = resolve_table_field_name(
        api,
        ctx.app_token,
        ctx.table_id,
        ctx.cycle_relist_field_name,
    )
    meta = get_table_field_meta(api, ctx.app_token, ctx.table_id)
    field_meta = meta.get(field_name) or meta.get(ctx.cycle_relist_field_name) or {}
    if is_checkbox_like_cycle_relist_field(field_meta):
        return {"field_name": field_name, "operator": "is", "value": [False]}
    return {"field_name": field_name, "operator": "isEmpty", "value": []}


def build_cycle_relist_candidate_search_filter(
    ctx: FailureLogTableContext,
    api: FeishuClient,
    *,
    completed_status: str,
) -> dict[str, Any]:
    """飞书 search filter：单个处理状态镜像 + 是否已循环上架未选（避免 children 嵌套触发 InvalidFilter）。"""
    status = str(completed_status or "").strip()
    if not status:
        raise ValueError("completed_status is required")

    mirror_field = resolve_table_field_name(
        api,
        ctx.app_token,
        ctx.table_id,
        ctx.mirror_field_name,
    )
    return {
        "conjunction": "and",
        "conditions": [
            {
                "field_name": mirror_field,
                "operator": "is",
                "value": [status],
            },
            build_cycle_relist_empty_condition(api, ctx),
        ],
    }


def parse_failure_log_record(
    record: dict[str, Any],
    ctx: FailureLogTableContext,
) -> dict[str, Any]:
    names = ctx.names
    fields = record.get("fields") or {}
    mirror_text = format_plain_text(fields.get(ctx.mirror_field_name))
    processor_names = format_user_names(fields.get(names.processor))
    processed_at = format_datetime_ms(fields.get(names.processed_at))
    status = resolve_process_status(mirror_text=mirror_text)
    account_name, account_id = read_failure_log_account(
        fields,
        account_name_field=ctx.account_name_field,
        account_id_field=ctx.account_id_field,
    )
    return {
        "record_id": str(record.get("record_id") or record.get("id") or ""),
        "date": format_datetime_ms(fields.get(names.date)) or str(fields.get(names.date) or ""),
        "merchant_code": str(fields.get(names.merchant_code) or ""),
        "report_platform": format_single_select(fields.get(names.report_platform)),
        "account_name": account_name,
        "account_id": account_id,
        "record_type": format_single_select(fields.get(names.record_type)),
        "failure_reason": str(fields.get(names.failure_reason) or ""),
        "publish_start": format_datetime_ms(fields.get(names.publish_start)),
        "publish_end": format_datetime_ms(fields.get(names.publish_end)),
        "duration_seconds": str(fields.get(names.duration_seconds) or ""),
        "process_completed": {
            "field_name": ctx.mirror_field_name,
            "label": status["label"],
            "source": status["source"],
            "mirror_text": mirror_text,
        },
        "cycle_relist": format_single_select(fields.get(ctx.cycle_relist_field_name)),
        "cycle_relist_field_name": ctx.cycle_relist_field_name,
        "processor": processor_names,
        "processed_at": processed_at,
        "fields_raw": fields,
    }


def list_pdd_failure_logs(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    api = client or FeishuClient(cfg)

    resolved = resolve_failure_log_table_context(cfg, api)
    if isinstance(resolved, dict):
        return resolved
    ctx = resolved

    max_items = max(1, min(int(limit), 500))
    raw_records = list_all_records(api, ctx.app_token, ctx.table_id, page_size=max_items)
    if len(raw_records) > max_items:
        raw_records = raw_records[:max_items]

    items = [parse_failure_log_record(record, ctx) for record in raw_records]

    mirror_readable = any(
        bool((row.get("process_completed") or {}).get("mirror_text"))
        for row in items
    )

    return {
        "ok": True,
        "app_token": ctx.app_token,
        "table_id": ctx.table_id,
        "table_name": ctx.table_name,
        "resolve_method": ctx.resolve_method,
        "mirror_field_name": ctx.mirror_field_name,
        "account_name_field": ctx.account_name_field,
        "account_id_field": ctx.account_id_field,
        "cycle_relist_field_name": ctx.cycle_relist_field_name,
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
            for f in list_fields(api, ctx.app_token, ctx.table_id)
        ],
    }


def list_platform_skip_records(
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    report_platform: str = "拼多多",
    failure_reason: str = PLATFORM_SKIP_REASON,
    fetch_limit: int | None = None,
) -> list[dict[str, str]]:
    """读取失败日志表中「平台不适用自动跳过」的拼多多商品编码（全店铺去重）。"""
    cfg = config or load_feishu_config()
    api = client or FeishuClient(cfg)
    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token:
        return []

    table_id, _, _ = _resolve_failure_log_table(cfg, api)
    if not table_id:
        return []

    names = cfg.pdd_upload_log.failure_field_names
    limit = fetch_limit
    if limit is None:
        limit = int(cfg.pipeline.platform_skip_dedupe_fetch_limit or 2000)
    limit = max(1, min(int(limit), 5000))

    raw_records = list_all_records(api, app_token, table_id, page_size=min(limit, 500))
    if len(raw_records) > limit:
        raw_records = raw_records[:limit]

    target_platform = str(report_platform or "拼多多").strip()
    target_reason = str(failure_reason or PLATFORM_SKIP_REASON).strip()
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in raw_records:
        fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
        platform = format_single_select(fields.get(names.report_platform))
        reason = str(fields.get(names.failure_reason) or "").strip()
        if platform != target_platform:
            continue
        if reason != target_reason:
            continue
        merchant_code = normalize_listing_code(str(fields.get(names.merchant_code) or ""))
        if not merchant_code:
            continue
        dedupe_key = f"{platform}|{merchant_code}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        records.append(
            {
                "merchant_code": merchant_code,
                "report_platform": platform,
            }
        )
    return records


def list_platform_skip_merchant_codes(
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    report_platform: str = "拼多多",
    failure_reason: str = PLATFORM_SKIP_REASON,
    fetch_limit: int | None = None,
) -> list[str]:
    """兼容旧调用：仅返回商品编码列表。"""
    records = list_platform_skip_records(
        config=config,
        client=client,
        report_platform=report_platform,
        failure_reason=failure_reason,
        fetch_limit=fetch_limit,
    )
    return list(dict.fromkeys(item["merchant_code"] for item in records if item.get("merchant_code")))

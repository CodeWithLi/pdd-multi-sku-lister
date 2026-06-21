"""PDD活动日志表 — 仅记录上架成功后的活动步骤（限时限量购 / 618 / 七折，一行一商品）。

时序：
1. 上架成功 → 同步预建行（日期 + 店铺名称 + 商品ID + 各活动「未执行」）
2. 限时限量购（上架后紧接）→ 只更新限时限量购列；行应已预建
3. 618 / 七折（可能延迟 24h）→ 只更新对应活动列；按店铺名称 + 商品ID 定位已有行
"""

from __future__ import annotations

import re
import threading
import time
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
    map_fields_to_table_names,
    search_records_by_field,
)
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    load_feishu_config,
    save_pdd_activity_table_id_to_config,
)
from pdd_agent.integrations.feishu.pdd_upload_sync import (
    _coerce_bitable_text,
    _resolve_or_create_pdd_table_id,
    lookup_pdd_upload_log_identity_fields,
)

logger = get_logger(__name__)

_INVALID_FILTER_CODES = frozenset({1254018})

_LIMITED_TIME_ONGOING = "进行中"
_LIMITED_TIME_FAILURE = "失败"
_LIMITED_TIME_PENDING = "未执行"
_ACTIVITY_REGISTER_SUCCESS = "报名成功"
_ACTIVITY_REGISTER_FAILURE = "失败"
_ACTIVITY_REGISTER_PENDING = "未执行"


def _date_to_ms(day: date) -> int:
    return int(datetime.combine(day, dt_time.min).timestamp() * 1000)


def _resolve_account_display_name(account_id: str, config: FeishuConfig) -> str:
    from pdd_agent.core.config import load_yaml_settings
    from pdd_agent.db.repositories import get_account_config

    settings = load_yaml_settings()
    account = get_account_config(settings, account_id)
    if account and str(account.username or "").strip():
        return str(account.username).strip()
    return str(account_id or "").strip()


def _brief_activity_failure_reason(error: str) -> str:
    text = str(error or "").strip()
    if not text:
        return ""
    try:
        from pdd_agent.skills.campaign.marketing_activities import (
            normalize_activity_register_failure_for_feishu,
        )

        normalized = normalize_activity_register_failure_for_feishu(text)
        if normalized:
            return normalized[:500]
    except Exception:
        pass
    if "中文解释:" in text:
        match = re.search(r"中文解释:\s*(.+?)(?:\n|$)", text)
        if match:
            return match.group(1).strip()[:500]
    line = text.split("\n")[0].strip()
    if line.startswith("错误码:"):
        for key in ("中文解释:", "原始报错:"):
            if key in text:
                part = text.split(key, 1)[-1].split("\n")[0].strip()
                if part:
                    return part[:500]
    return line[:500]


def map_limited_time_activity_status(*, success: bool) -> str:
    return _LIMITED_TIME_ONGOING if success else _LIMITED_TIME_FAILURE


def map_activity_register_activity_status(*, success: bool) -> str:
    return _ACTIVITY_REGISTER_SUCCESS if success else _ACTIVITY_REGISTER_FAILURE


def resolve_activity_log_phase(activity_id: str, config: FeishuConfig | None = None) -> str:
    """返回 limited_time / activity_618 / activity_discount / unknown。"""
    cfg = config or load_feishu_config()
    activity_cfg = cfg.pdd_activity_log
    aid = str(activity_id or "").strip()
    if aid == str(activity_cfg.activity_618_id or "20981").strip():
        return "activity_618"
    if aid == str(activity_cfg.activity_discount_id or "21365").strip():
        return "activity_discount"
    return "unknown"


def _field_defs_for_pdd_activity_log(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.pdd_activity_log.field_names
    activity_cfg = config.pdd_activity_log
    return [
        {
            "field_name": names.date,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False},
        },
        {"field_name": names.account_name, "type": FIELD_TEXT},
        {"field_name": names.product_id, "type": FIELD_TEXT},
        {
            "field_name": names.limited_time_status,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in activity_cfg.limited_time_status_options]},
        },
        {"field_name": names.limited_time_failure_reason, "type": FIELD_TEXT},
        {
            "field_name": names.activity_618_status,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in activity_cfg.activity_register_status_options]},
        },
        {"field_name": names.activity_618_failure_reason, "type": FIELD_TEXT},
        {
            "field_name": names.activity_discount_status,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in activity_cfg.activity_register_status_options]},
        },
        {"field_name": names.activity_discount_failure_reason, "type": FIELD_TEXT},
    ]


def resolve_pdd_activity_log_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
    create_if_missing: bool = False,
) -> tuple[str, str]:
    activity_cfg = cfg.pdd_activity_log
    return _resolve_or_create_pdd_table_id(
        cfg,
        client,
        configured_id=activity_cfg.table_id,
        table_name=activity_cfg.table_name,
        save_table_id=save_table_id,
        save_fn=save_pdd_activity_table_id_to_config,
        create_if_missing=create_if_missing,
    )


def ensure_pdd_activity_log_table_ready(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    activity_cfg = cfg.pdd_activity_log
    if not activity_cfg.enabled:
        return {"skipped": True, "reason": "pdd_activity_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_activity_log_table_id(
        cfg, api, save_table_id=True, create_if_missing=True
    )
    if not table_id:
        return {
            "failed": True,
            "reason": "table_not_found",
            "message": f"未找到或无法创建飞书表「{activity_cfg.table_name}」",
        }

    ensure_fields(api, app_token, table_id, _field_defs_for_pdd_activity_log(cfg))
    logger.info("pdd activity log fields ensured table=%s method=%s", table_id, resolve_method)
    print(
        f"[feishu] PDD活动日志表字段已就绪：{activity_cfg.table_name} ({table_id})",
        flush=True,
    )
    return {"ready": True, "table_id": table_id, "resolve_method": resolve_method}


def _resolve_store_name(
    *,
    account_id: str,
    account_name: str = "",
    config: FeishuConfig,
) -> str:
    return str(account_name or "").strip() or _resolve_account_display_name(account_id, config)


def _find_activity_log_record(
    client: FeishuClient,
    *,
    app_token: str,
    table_id: str,
    config: FeishuConfig,
    product_id: str,
    account_id: str = "",
    account_name: str = "",
    retries: int,
    interval_seconds: float,
) -> dict[str, Any] | None:
    """按商品ID检索，并用店铺名称匹配定位唯一行。"""
    product_id = str(product_id or "").strip()
    if not product_id:
        return None
    names = config.pdd_activity_log.field_names
    dedupe_field = str(config.pdd_activity_log.dedupe_field or names.product_id or "商品ID").strip()
    store_name = _resolve_store_name(account_id=account_id, account_name=account_name, config=config)
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            rows = search_records_by_field(
                client,
                app_token,
                table_id,
                field_name=dedupe_field,
                value=product_id,
            )
        except FeishuAPIError as exc:
            if exc.code in _INVALID_FILTER_CODES:
                return None
            raise
        for row in rows:
            fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
            row_store = _coerce_bitable_text(fields.get(names.account_name))
            if not store_name or row_store == store_name:
                return row
        if attempt + 1 < attempts:
            time.sleep(max(0.5, float(interval_seconds)))
    return None


def _activity_log_patch_unchanged(existing_fields: dict[str, Any], mapped_patch: dict[str, Any]) -> bool:
    existing = existing_fields if isinstance(existing_fields, dict) else {}
    for key, new_value in mapped_patch.items():
        if _coerce_bitable_text(existing.get(key)) != _coerce_bitable_text(new_value):
            return False
    return True


def _build_activity_log_base_fields(
    *,
    config: FeishuConfig,
    account_id: str,
    product_id: str,
    account_name: str = "",
    activity_at: datetime | None = None,
) -> dict[str, Any]:
    names = config.pdd_activity_log.field_names
    when = activity_at or datetime.now()
    store_name = _resolve_store_name(account_id=account_id, account_name=account_name, config=config)
    return {
        names.date: _date_to_ms(when.date()),
        names.account_name: store_name,
        names.product_id: str(product_id or "").strip(),
        names.limited_time_status: _LIMITED_TIME_PENDING,
        names.limited_time_failure_reason: "",
        names.activity_618_status: _ACTIVITY_REGISTER_PENDING,
        names.activity_618_failure_reason: "",
        names.activity_discount_status: _ACTIVITY_REGISTER_PENDING,
        names.activity_discount_failure_reason: "",
    }


def load_activity_log_product_context(
    account_id: str,
    product_ids: list[str],
    *,
    config: FeishuConfig | None = None,
) -> dict[str, dict[str, str]]:
    """批量解析店铺名称（同一任务下各商品共用）。"""
    cfg = config or load_feishu_config()
    store = _resolve_store_name(account_id=account_id, account_name="", config=cfg)
    return {
        pid: {"account_name": store}
        for pid in dict.fromkeys(str(x or "").strip() for x in product_ids if str(x or "").strip())
    }


def safe_load_activity_log_product_context(
    account_id: str,
    product_ids: list[str],
    *,
    account_name: str = "",
    config: FeishuConfig | None = None,
) -> dict[str, dict[str, str]]:
    """解析店铺名称；失败时回退 account_name / account_id，不抛异常。"""
    cfg = config or load_feishu_config()
    try:
        return load_activity_log_product_context(account_id, product_ids, config=cfg)
    except Exception as exc:
        logger.warning(
            "load activity log product context failed account=%s: %s",
            account_id,
            exc,
        )
    store = str(account_name or "").strip()
    if not store:
        try:
            store = _resolve_account_display_name(account_id, cfg)
        except Exception:
            store = str(account_id or "").strip()
    return {
        pid: {"account_name": store}
        for pid in dict.fromkeys(str(x or "").strip() for x in product_ids if str(x or "").strip())
    }


def _resolve_activity_log_identity(
    *,
    product_id: str,
    account_id: str = "",
    account_name: str = "",
    activity_at: datetime | None = None,
    identity_mode: str = "delayed",
    config: FeishuConfig,
    client: FeishuClient,
) -> dict[str, Any]:
    an = _resolve_store_name(account_id=account_id, account_name=account_name, config=config)
    if not an:
        if identity_mode == "immediate":
            upload_retries = config.pdd_upload_log.limited_time_lookup_retries
            upload_interval = config.pdd_upload_log.limited_time_lookup_interval_seconds
        else:
            upload_retries = config.pdd_activity_log.lookup_retries
            upload_interval = config.pdd_activity_log.lookup_interval_seconds
        ctx = lookup_pdd_upload_log_identity_fields(
            product_id,
            config=config,
            client=client,
            retries=upload_retries,
            interval_seconds=upload_interval,
        )
        an = str(ctx.get("account_name") or "").strip() or _resolve_account_display_name(account_id, config)

    return _build_activity_log_base_fields(
        config=config,
        account_id=account_id,
        product_id=product_id,
        account_name=an,
        activity_at=activity_at,
    )


def push_pdd_activity_log_seed(
    *,
    account_id: str = "",
    product_id: str = "",
    account_name: str = "",
    seeded_at: datetime | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """上架成功后预建活动日志行（幂等：已有行则跳过，不覆盖已执行的活动状态）。"""
    cfg = config or load_feishu_config()
    activity_cfg = cfg.pdd_activity_log
    if not activity_cfg.enabled or not activity_cfg.seed_on_listing:
        return {"skipped": True, "reason": "activity_log_seed_disabled"}

    pid = str(product_id or "").strip()
    if not pid:
        return {"skipped": True, "reason": "missing_product_id"}

    api = client or FeishuClient(cfg)
    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    table_id, resolve_method = resolve_pdd_activity_log_table_id(
        cfg, api, save_table_id=True, create_if_missing=True
    )
    if not table_id:
        return {"failed": True, "reason": "table_not_found"}

    ensure_fields(api, app_token, table_id, _field_defs_for_pdd_activity_log(cfg))
    existing = _find_activity_log_record(
        api,
        app_token=app_token,
        table_id=table_id,
        config=cfg,
        product_id=pid,
        account_id=account_id,
        account_name=account_name,
        retries=1,
        interval_seconds=0.5,
    )
    if existing:
        return {
            "skipped": True,
            "reason": "already_seeded",
            "record_id": str(existing.get("record_id") or ""),
            "product_id": pid,
        }

    fields = _resolve_activity_log_identity(
        product_id=pid,
        account_id=account_id,
        account_name=account_name,
        activity_at=seeded_at,
        identity_mode="immediate",
        config=cfg,
        client=api,
    )
    mapped = map_fields_to_table_names(api, app_token, table_id, fields)
    record_ids = batch_create_records(api, app_token, table_id, [mapped])
    record_id = record_ids[0] if record_ids else ""
    logger.info("feishu pdd activity log seeded product_id=%s table=%s(%s)", pid, table_id, resolve_method)
    return {
        "created": True,
        "record_id": record_id,
        "table_id": table_id,
        "product_id": pid,
    }


def upsert_pdd_activity_log_fields(
    *,
    product_id: str,
    patch_fields: dict[str, Any],
    account_id: str = "",
    account_name: str = "",
    activity_at: datetime | None = None,
    identity_mode: str = "delayed",
    find_retries: int | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """按店铺名称 + 商品ID 更新 PDD活动日志表；不存在则按活动步骤创建。"""
    cfg = config or load_feishu_config()
    activity_cfg = cfg.pdd_activity_log
    if not activity_cfg.enabled:
        return {"skipped": True, "reason": "pdd_activity_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    pid = str(product_id or "").strip()
    if not pid:
        return {"skipped": True, "reason": "missing_product_id"}

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_activity_log_table_id(
        cfg, api, save_table_id=True, create_if_missing=True
    )
    if not table_id:
        msg = f"未找到飞书表「{activity_cfg.table_name}」"
        return {"failed": True, "reason": "table_not_found", "message": msg}

    ensure_fields(api, app_token, table_id, _field_defs_for_pdd_activity_log(cfg))

    mapped_patch = map_fields_to_table_names(api, app_token, table_id, patch_fields)
    resolved_find_retries = max(
        1,
        int(
            find_retries
            if find_retries is not None
            else (
                activity_cfg.immediate_find_retries
                if identity_mode == "immediate"
                else activity_cfg.lookup_retries
            )
        ),
    )
    find_interval = (
        0.5
        if identity_mode == "immediate"
        else activity_cfg.lookup_interval_seconds
    )
    existing = _find_activity_log_record(
        api,
        app_token=app_token,
        table_id=table_id,
        config=cfg,
        product_id=pid,
        account_id=account_id,
        account_name=account_name,
        retries=resolved_find_retries,
        interval_seconds=find_interval,
    )

    if existing:
        record_id = str(existing.get("record_id") or "").strip()
        if not record_id:
            return {"failed": True, "reason": "missing_record_id"}
        existing_fields = existing.get("fields") if isinstance(existing.get("fields"), dict) else {}
        if _activity_log_patch_unchanged(existing_fields, mapped_patch):
            logger.debug(
                "feishu pdd activity log unchanged product_id=%s table=%s fields=%s",
                pid,
                table_id,
                list(mapped_patch.keys()),
            )
            return {
                "updated": False,
                "created": False,
                "skipped": True,
                "reason": "unchanged",
                "record_id": record_id,
                "table_id": table_id,
                "product_id": pid,
                "fields": mapped_patch,
            }
        batch_update_records(
            api,
            app_token,
            table_id,
            [{"record_id": record_id, "fields": mapped_patch}],
        )
        logger.info(
            "feishu pdd activity log updated product_id=%s table=%s(%s) fields=%s",
            pid,
            table_id,
            resolve_method,
            list(mapped_patch.keys()),
        )
        return {
            "updated": True,
            "created": False,
            "record_id": record_id,
            "table_id": table_id,
            "product_id": pid,
            "fields": mapped_patch,
        }

    base_fields = _resolve_activity_log_identity(
        product_id=pid,
        account_id=account_id,
        account_name=account_name,
        activity_at=activity_at,
        identity_mode=identity_mode,
        config=cfg,
        client=api,
    )
    create_fields = dict(base_fields)
    create_fields.update(patch_fields)

    mapped_create = map_fields_to_table_names(api, app_token, table_id, create_fields)
    record_ids = batch_create_records(api, app_token, table_id, [mapped_create])
    record_id = record_ids[0] if record_ids else ""
    logger.info(
        "feishu pdd activity log created product_id=%s table=%s(%s)",
        pid,
        table_id,
        resolve_method,
    )
    print(
        f"[{account_id or '-'}] [{pid}] 飞书 PDD活动日志表已新建 record_id={record_id}",
        flush=True,
    )
    return {
        "updated": False,
        "created": True,
        "record_id": record_id,
        "record_ids": record_ids,
        "table_id": table_id,
        "product_id": pid,
        "fields": mapped_create,
    }


def _account_name_for_push(
    *,
    product_contexts: dict[str, dict[str, str]] | None,
    account_id: str,
    account_name: str = "",
    config: FeishuConfig,
) -> str:
    ctx_name = ""
    if product_contexts:
        for item in product_contexts.values():
            ctx_name = str(item.get("account_name") or "").strip()
            if ctx_name:
                break
    return _resolve_store_name(
        account_id=account_id,
        account_name=account_name or ctx_name,
        config=config,
    )


def push_pdd_activity_log_limited_time(
    *,
    account_id: str = "",
    product_ids: list[str],
    success: bool,
    error: str = "",
    account_name: str = "",
    product_contexts: dict[str, dict[str, str]] | None = None,
    product_errors: dict[str, str] | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    names = cfg.pdd_activity_log.field_names
    status_value = map_limited_time_activity_status(success=success)
    default_reason = "" if success else _brief_activity_failure_reason(error)

    store_name = _account_name_for_push(
        product_contexts=product_contexts,
        account_id=account_id,
        account_name=account_name,
        config=cfg,
    )

    results: list[dict[str, Any]] = []
    missing: list[str] = []
    for pid in dict.fromkeys(str(x or "").strip() for x in product_ids if str(x or "").strip()):
        row_reason = default_reason
        if not success and product_errors:
            row_reason = _brief_activity_failure_reason(product_errors.get(pid) or error)
        patch = {
            names.limited_time_status: status_value,
            names.limited_time_failure_reason: row_reason,
        }
        row_store = str((product_contexts or {}).get(pid, {}).get("account_name") or store_name).strip()
        row = upsert_pdd_activity_log_fields(
            product_id=pid,
            patch_fields=patch,
            account_id=account_id,
            account_name=row_store,
            identity_mode="immediate",
            config=cfg,
            client=client,
        )
        results.append(row)
        if row.get("skipped") or row.get("failed"):
            missing.append(pid)

    updated = sum(1 for row in results if row.get("updated") or row.get("created"))
    return {
        "updated_count": updated,
        "status": status_value,
        "product_ids": list(dict.fromkeys(product_ids)),
        "missing_product_ids": missing,
        "results": results,
    }


def push_pdd_activity_log_activity_register(
    *,
    account_id: str = "",
    activity_id: str,
    product_ids: list[str],
    success: bool,
    error: str = "",
    account_name: str = "",
    product_contexts: dict[str, dict[str, str]] | None = None,
    product_errors: dict[str, str] | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    phase = resolve_activity_log_phase(activity_id, cfg)
    if phase == "unknown":
        return {"skipped": True, "reason": "activity_not_configured", "activity_id": activity_id}

    names = cfg.pdd_activity_log.field_names
    status_value = map_activity_register_activity_status(success=success)
    default_reason = "" if success else _brief_activity_failure_reason(error)

    if phase == "activity_618":
        status_field = names.activity_618_status
        reason_field = names.activity_618_failure_reason
    else:
        status_field = names.activity_discount_status
        reason_field = names.activity_discount_failure_reason

    store_name = _account_name_for_push(
        product_contexts=product_contexts,
        account_id=account_id,
        account_name=account_name,
        config=cfg,
    )

    results: list[dict[str, Any]] = []
    missing: list[str] = []
    for pid in dict.fromkeys(str(x or "").strip() for x in product_ids if str(x or "").strip()):
        row_reason = default_reason
        if not success and product_errors:
            row_reason = _brief_activity_failure_reason(product_errors.get(pid) or error)
        patch = {
            status_field: status_value,
            reason_field: row_reason,
        }
        row_store = str((product_contexts or {}).get(pid, {}).get("account_name") or store_name).strip()
        row = upsert_pdd_activity_log_fields(
            product_id=pid,
            patch_fields=patch,
            account_id=account_id,
            account_name=row_store,
            identity_mode="delayed",
            config=cfg,
            client=client,
        )
        results.append(row)
        if row.get("skipped") or row.get("failed"):
            missing.append(pid)

    updated = sum(1 for row in results if row.get("updated") or row.get("created"))
    return {
        "updated_count": updated,
        "phase": phase,
        "activity_id": str(activity_id or "").strip(),
        "status": status_value,
        "product_ids": list(dict.fromkeys(product_ids)),
        "missing_product_ids": missing,
        "results": results,
    }


def _push_pdd_activity_log_safe(*, log_label: str, push_fn: Any, **kwargs: Any) -> None:
    account_id = str(kwargs.get("account_id") or "")
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            result = push_fn(**kwargs)
            if result.get("updated") or result.get("created") or result.get("updated_count"):
                print(f"[{account_id}] 飞书{log_label}已回写", flush=True)
            elif result.get("skipped") and result.get("reason") != "unchanged":
                logger.info("feishu %s skipped: %s", log_label, result.get("reason"))
            elif result.get("failed"):
                print(f"[{account_id}] 飞书{log_label}失败：{result.get('message') or result.get('reason')}", flush=True)
            return
        except Exception as exc:
            last_exc = exc
            if attempt + 1 >= 3:
                logger.exception("feishu %s failed account=%s", log_label, account_id)
                print(f"[{account_id}] 飞书{log_label}失败：{exc}", flush=True)
                return
            time.sleep(0.8 * (attempt + 1))


def schedule_pdd_activity_log_seed(**kwargs: Any) -> None:
    """上架成功后预建活动日志行；与发布日志表同样走同步写入，供紧接的限时限量购使用。"""
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_activity_log.enabled or not cfg.pdd_activity_log.seed_on_listing:
        return
    if cfg.pdd_upload_log.sync_on_listing:
        _push_pdd_activity_log_safe(
            log_label="PDD活动日志(预建)",
            push_fn=push_pdd_activity_log_seed,
            **kwargs,
        )
        return
    thread = threading.Thread(
        target=_push_pdd_activity_log_safe,
        kwargs={
            "log_label": "PDD活动日志(预建)",
            "push_fn": push_pdd_activity_log_seed,
            **kwargs,
        },
        name="feishu-pdd-activity-log-seed",
        daemon=True,
    )
    thread.start()


def schedule_pdd_activity_log_limited_time(**kwargs: Any) -> None:
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_activity_log.enabled:
        return
    push_kwargs = {
        "log_label": "PDD活动日志(限时限量购)",
        "push_fn": push_pdd_activity_log_limited_time,
        **kwargs,
    }
    # 失败同步写入，确保任何报错都落表（与 PDD 发布失败日志一致）
    if not bool(kwargs.get("success")):
        _push_pdd_activity_log_safe(**push_kwargs)
        return
    thread = threading.Thread(
        target=_push_pdd_activity_log_safe,
        kwargs=push_kwargs,
        name="feishu-pdd-activity-log-limited-time",
        daemon=True,
    )
    thread.start()


def schedule_pdd_activity_log_activity_register(**kwargs: Any) -> None:
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_activity_log.enabled:
        return
    activity_id = str(kwargs.get("activity_id") or "").strip()
    if resolve_activity_log_phase(activity_id, cfg) == "unknown":
        return
    push_kwargs = {
        "log_label": f"PDD活动日志(活动{activity_id})",
        "push_fn": push_pdd_activity_log_activity_register,
        **kwargs,
    }
    if not bool(kwargs.get("success")):
        _push_pdd_activity_log_safe(**push_kwargs)
        return
    thread = threading.Thread(
        target=_push_pdd_activity_log_safe,
        kwargs=push_kwargs,
        name="feishu-pdd-activity-log-register",
        daemon=True,
    )
    thread.start()

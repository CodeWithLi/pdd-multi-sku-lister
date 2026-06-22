"""PDD 推广日志表 — 推广创建成功/失败写入同一张飞书表。"""

from __future__ import annotations

import threading
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import (
    FIELD_DATETIME,
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
    save_pdd_promotion_table_id_to_config,
)
from pdd_agent.integrations.feishu.pdd_upload_sync import _resolve_or_create_pdd_table_id
from pdd_agent.skills.traffic.promotion_create import (
    PROMOTION_SEARCH_EMPTY_FEISHU_MESSAGE,
    normalize_promotion_failure_for_feishu,
)

logger = get_logger(__name__)

_PROMOTION_SUCCESS = "成功"
_PROMOTION_FAILURE = "失败"


def _date_to_ms(day: date) -> int:
    return int(datetime.combine(day, dt_time.min).timestamp() * 1000)


def _resolve_account_display_name(account_id: str, config: FeishuConfig) -> str:
    from pdd_agent.core.account_display import resolve_account_display_name

    return resolve_account_display_name(account_id)


def _field_defs_for_promotion_log(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.pdd_promotion_log.field_names
    promo_cfg = config.pdd_promotion_log
    return [
        {
            "field_name": names.date,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False},
        },
        {"field_name": names.account_name, "type": FIELD_TEXT},
        {"field_name": names.product_id, "type": FIELD_TEXT},
        {
            "field_name": names.result,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in promo_cfg.result_options]},
        },
        {"field_name": names.message, "type": FIELD_TEXT},
        {"field_name": names.failure_reason, "type": FIELD_TEXT},
        {"field_name": names.run_id, "type": FIELD_TEXT},
    ]


def resolve_pdd_promotion_log_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
    create_if_missing: bool = False,
) -> tuple[str, str]:
    promo_cfg = cfg.pdd_promotion_log
    return _resolve_or_create_pdd_table_id(
        cfg,
        client,
        configured_id=promo_cfg.table_id,
        table_name=promo_cfg.table_name,
        save_table_id=save_table_id,
        save_fn=save_pdd_promotion_table_id_to_config,
        create_if_missing=create_if_missing,
    )


def ensure_pdd_promotion_log_table_ready(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    promo_cfg = cfg.pdd_promotion_log
    if not promo_cfg.enabled:
        return {"skipped": True, "reason": "pdd_promotion_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_promotion_log_table_id(
        cfg, api, save_table_id=True, create_if_missing=True
    )
    if not table_id:
        return {
            "failed": True,
            "reason": "table_not_found",
            "message": f"未找到或无法创建飞书表「{promo_cfg.table_name}」",
        }

    ensure_fields(api, app_token, table_id, _field_defs_for_promotion_log(cfg))
    logger.info("pdd promotion log table ready table=%s(%s)", table_id, resolve_method)
    return {
        "ready": True,
        "table_id": table_id,
        "resolve_method": resolve_method,
    }


# 兼容旧调用名
ensure_pdd_promotion_log_tables_ready = ensure_pdd_promotion_log_table_ready


def _collect_selected_product_ids(result: dict[str, Any] | None) -> list[str]:
    payload = result if isinstance(result, dict) else {}
    ids: list[str] = []
    for key in ("selected_pdd_product_ids", "pdd_product_ids"):
        for item in payload.get(key) or []:
            text = str(item or "").strip()
            if text and text not in ids:
                ids.append(text)
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        for key in ("selected_pdd_product_ids", "found_product_ids", "requested_product_ids"):
            for value in item.get(key) or []:
                text = str(value or "").strip()
                if text and text not in ids:
                    ids.append(text)
    return ids


def _extract_failure_step_and_error(result: dict[str, Any] | None) -> tuple[str, str]:
    payload = result if isinstance(result, dict) else {}
    top_error = str(payload.get("error") or "").strip()
    if top_error:
        return str(payload.get("step") or "").strip(), top_error
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") == "success":
            continue
        step = str(item.get("step") or "").strip()
        error = str(item.get("error") or "").strip()
        if error:
            return step, error
    errors = payload.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            text = str(item or "").strip()
            if text:
                return "", text
    return "", "推广任务失败"


def build_promotion_log_entries(
    *,
    selected_product_ids: list[str],
    result: dict[str, Any] | None,
    success: bool,
) -> tuple[list[str], dict[str, str]]:
    """返回 (商品ID列表, {product_id: 备注/失败原因})。"""
    ids = list(
        dict.fromkeys(
            str(item or "").strip()
            for item in (selected_product_ids or _collect_selected_product_ids(result))
            if str(item or "").strip()
        )
    )
    messages: dict[str, str] = {}
    if success:
        payload = result if isinstance(result, dict) else {}
        summary = str(payload.get("message") or "").strip()
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                continue
            edit_result = item.get("edit_bid_result") if isinstance(item.get("edit_bid_result"), dict) else item
            if isinstance(edit_result, dict):
                summary = summary or str(edit_result.get("message") or "").strip()
                for pid in edit_result.get("found_product_ids") or []:
                    text = str(pid or "").strip()
                    if text:
                        messages[text] = summary or "推广创建成功"
        for pid in ids:
            messages.setdefault(pid, summary or "推广创建成功")
        return ids, messages

    step, error = _extract_failure_step_and_error(result)
    brief = normalize_promotion_failure_for_feishu(error=error, step=step)
    for pid in ids:
        messages[pid] = brief
    if not ids:
        messages[""] = brief
    return ids, messages


def push_pdd_promotion_log(
    *,
    account_id: str = "",
    product_ids: list[str],
    success: bool,
    result: dict[str, Any] | None = None,
    error: str = "",
    run_id: str = "",
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    promo_cfg = cfg.pdd_promotion_log
    if not promo_cfg.enabled:
        return {"skipped": True, "reason": "pdd_promotion_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    ids, messages = build_promotion_log_entries(
        selected_product_ids=product_ids,
        result=result,
        success=success,
    )
    if not ids and not messages:
        return {"skipped": True, "reason": "missing_product_ids"}

    if not ids and messages:
        ids = [""]

    account_name = _resolve_account_display_name(account_id, cfg)
    api = client or FeishuClient(cfg)
    ready = ensure_pdd_promotion_log_table_ready(cfg, api)
    if ready.get("failed") or ready.get("skipped"):
        return ready

    names = promo_cfg.field_names
    today = _date_to_ms(datetime.now().date())
    table_id = str(ready.get("table_id") or "")
    rows: list[dict[str, Any]] = []
    fallback = normalize_promotion_failure_for_feishu(error=error)

    for pid in ids:
        if success:
            rows.append(
                {
                    names.date: today,
                    names.account_name: account_name,
                    names.product_id: pid,
                    names.result: _PROMOTION_SUCCESS,
                    names.message: str(messages.get(pid) or "推广创建成功").strip()[:500],
                    names.failure_reason: "",
                    names.run_id: str(run_id or "").strip(),
                }
            )
        else:
            reason = str(messages.get(pid) or fallback or "推广任务失败").strip()[:500]
            rows.append(
                {
                    names.date: today,
                    names.account_name: account_name,
                    names.product_id: pid,
                    names.result: _PROMOTION_FAILURE,
                    names.message: "",
                    names.failure_reason: reason,
                    names.run_id: str(run_id or "").strip(),
                }
            )

    mapped_rows = [map_fields_to_table_names(api, app_token, table_id, row) for row in rows]
    try:
        record_ids = batch_create_records(api, app_token, table_id, mapped_rows)
    except FeishuAPIError as exc:
        logger.exception("push pdd promotion log failed account=%s success=%s", account_id, success)
        return {"failed": True, "error": str(exc), "code": exc.code}

    logger.info(
        "pdd promotion log pushed account=%s success=%s rows=%s table=%s",
        account_id,
        success,
        len(record_ids),
        table_id,
    )
    return {
        "success": True,
        "created_count": len(record_ids),
        "record_ids": record_ids,
        "product_ids": ids,
        "table_id": table_id,
    }


def _push_pdd_promotion_log_safe(**kwargs: Any) -> None:
    account_id = str(kwargs.get("account_id") or "")
    try:
        result = push_pdd_promotion_log(**kwargs)
        if result.get("failed"):
            logger.error("[%s] feishu promotion log failed: %s", account_id, result)
        elif result.get("created_count"):
            print(
                f"[{account_id}] 飞书推广日志已写入 {result.get('created_count')} 条",
                flush=True,
            )
    except Exception:
        logger.exception("push pdd promotion log failed account=%s", account_id)


def schedule_pdd_promotion_log(**kwargs: Any) -> None:
    """推广任务完成后写入 PDD推广日志表；失败同步写入确保落表。"""
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_promotion_log.enabled:
        return

    if not bool(kwargs.get("success")):
        _push_pdd_promotion_log_safe(**kwargs)
        return

    thread = threading.Thread(
        target=_push_pdd_promotion_log_safe,
        kwargs=kwargs,
        name="feishu-pdd-promotion-log",
        daemon=True,
    )
    thread.start()


__all__ = [
    "PROMOTION_SEARCH_EMPTY_FEISHU_MESSAGE",
    "build_promotion_log_entries",
    "ensure_pdd_promotion_log_table_ready",
    "ensure_pdd_promotion_log_tables_ready",
    "push_pdd_promotion_log",
    "schedule_pdd_promotion_log",
]

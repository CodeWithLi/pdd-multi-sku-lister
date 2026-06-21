"""LangGraph 任务执行服务。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.agents.campaign import build_campaign_graph
from pdd_agent.agents.delist import build_delist_graph
from pdd_agent.agents.listing import build_listing_graph
from pdd_agent.agents.orchestrator import build_orchestrator_graph
from pdd_agent.agents.traffic import build_traffic_graph
from pdd_agent.api.schemas.tasks import PlanResponse
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    get_account_config,
    get_published_product_by_mapping_id,
    patch_published_product_spec_metadata,
    update_published_product_status,
    upsert_published_product,
)
from pdd_agent.skills.published.goods_list_lookup import lookup_published_product_in_goods_list
from pdd_agent.domain.enums import AgentKind, RunStatus, TaskPhase
from pdd_agent.domain.models import PlannedTask
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)

_DB_MESSAGE_MAX = 2000
_DB_LARGE_TEXT_MAX = 500
_LARGE_RESULT_TEXT_KEYS = frozenset({
    "pdd_product_matched_row_text",
    "matched_row_text",
    "row_text",
})


def _json_safe(value: Any) -> Any:
    """把 graph 返回值转为可 JSON 序列化的结构。"""
    if isinstance(value, PlannedTask):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _truncate_db_text(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(共{len(text)}字)"


def _compact_value_for_storage(value: Any, key: str = "") -> Any:
    """落库前截断页面抓取等超大文本，避免撑爆 run_records。"""
    if isinstance(value, str):
        if key in _LARGE_RESULT_TEXT_KEYS:
            return _truncate_db_text(value, _DB_LARGE_TEXT_MAX)
        if len(value) > 2000:
            return _truncate_db_text(value, 2000)
        return value
    if isinstance(value, list):
        return [_compact_value_for_storage(item, "") for item in value]
    if isinstance(value, dict):
        return {k: _compact_value_for_storage(v, k) for k, v in value.items()}
    return value


def _compact_run_result_for_storage(result: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(result)
    return compacted if isinstance(compacted, dict) else result


def _summarize_listing_message(result: dict[str, Any]) -> str:
    """上架任务 message 只存摘要，完整结果在 result 字段。"""
    errors = result.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            text = str(item or "").strip()
            if text:
                return _truncate_db_text(text, _DB_MESSAGE_MAX)
    items = [r for r in result.get("results") or [] if isinstance(r, dict)]
    if not items:
        return "上架任务完成"
    success = sum(1 for r in items if str(r.get("status") or "") in {"success", "listed"})
    failed = sum(1 for r in items if str(r.get("status") or "") == "failed")
    retryable = sum(1 for r in items if str(r.get("status") or "") == "retryable")
    parts = [f"共{len(items)}个单元", f"成功{success}", f"可重试{retryable}", f"失败{failed}"]
    for row in items:
        if str(row.get("status") or "") in {"success", "listed"}:
            continue
        label = str(row.get("listing_label") or "").strip()
        reason = str(row.get("reason") or row.get("error") or "").strip()
        if label or reason:
            parts.append(f"例：{label} {reason}".strip())
            break
    return _truncate_db_text("；".join(parts), _DB_MESSAGE_MAX)


def _summarize_delist_message(result: dict[str, Any]) -> str:
    errors = result.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            text = str(item or "").strip()
            if text:
                return _truncate_db_text(text, _DB_MESSAGE_MAX)
    items = result.get("results")
    if isinstance(items, list) and items:
        return _truncate_db_text(f"下架处理 {len(items)} 条", _DB_MESSAGE_MAX)
    return "下架任务完成"


def _summarize_campaign_message(result: dict[str, Any]) -> str:
    """活动任务失败时只存简短说明，避免把整份 results JSON 写入 message。"""
    top_error = str(result.get("error") or "").strip()
    if top_error:
        return top_error

    item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
    for item in item_results:
        reg_msg = _activity_registration_summary_line(item)
        if reg_msg:
            return reg_msg

    errors = result.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            text = str(item or "").strip()
            if text:
                return text
    for item in item_results:
        if str(item.get("status") or "") == "success":
            continue
        err = str(item.get("error") or "").strip()
        if err:
            step = str(item.get("step") or "").strip()
            return f"{step}: {err}" if step else err
    if item_results and all(str(r.get("status") or "") == "success" for r in item_results):
        return "活动任务已完成"
    return "活动任务失败"


def _campaign_failure_message(result: dict[str, Any], status: RunStatus) -> str:
    if status == RunStatus.SUCCESS:
        return ""
    return _summarize_campaign_message(result if isinstance(result, dict) else {})


_CANCEL_FAILURE_MESSAGE = "任务已取消（可能为手动关闭浏览器或用户取消）"

_feishu_terminal_logged_run_ids: set[str] = set()


def _feishu_already_logged_for_run(run_id: str) -> bool:
    return str(run_id or "").strip() in _feishu_terminal_logged_run_ids


def mark_feishu_terminal_logged(run_id: str) -> None:
    run_id = str(run_id or "").strip()
    if run_id:
        _feishu_terminal_logged_run_ids.add(run_id)


def _claim_feishu_terminal_log(run_id: str) -> bool:
    """乐观占位：同一 run 的飞书终态回写只允许一次（防 execute 与 reconcile 并发重复写）。"""
    run_id = str(run_id or "").strip()
    if not run_id:
        return True
    if run_id in _feishu_terminal_logged_run_ids:
        return False
    _feishu_terminal_logged_run_ids.add(run_id)
    return True


def _release_feishu_terminal_log(run_id: str) -> None:
    run_id = str(run_id or "").strip()
    if run_id:
        _feishu_terminal_logged_run_ids.discard(run_id)


def _normalize_terminal_failure_result(
    result: dict[str, Any] | None,
    *,
    error: str = "",
    run_status: RunStatus | None = None,
) -> dict[str, Any]:
    payload = dict(result) if isinstance(result, dict) else {}
    msg = str(error or payload.get("error") or "").strip()
    if run_status == RunStatus.CANCELED:
        msg = msg or _CANCEL_FAILURE_MESSAGE
        payload["error"] = msg
        errors = payload.get("errors")
        if not isinstance(errors, list):
            errors = []
        if msg and msg not in errors:
            errors.append(msg)
        payload["errors"] = errors
    elif msg and not payload.get("error"):
        payload["error"] = msg
    return payload


def _extract_per_product_activity_errors(
    result: dict[str, Any] | None,
    *,
    fallback_error: str = "",
    product_ids: list[str] | None = None,
) -> dict[str, str]:
    """从活动结果中解析各商品ID对应的失败原因（含24h限制、不可报名等）。"""
    from pdd_agent.skills.campaign.marketing_activities import (
        ACTIVITY_TIME_REQUIREMENT_FEISHU_MESSAGE,
        is_activity_time_requirement_text,
    )

    errors: dict[str, str] = {}
    fallback = str(fallback_error or "").strip()
    if is_activity_time_requirement_text(fallback):
        fallback = ACTIVITY_TIME_REQUIREMENT_FEISHU_MESSAGE

    for item in (result or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        item_error = str(item.get("error") or item.get("message") or "").strip()
        if is_activity_time_requirement_text(item_error):
            item_error = ACTIVITY_TIME_REQUIREMENT_FEISHU_MESSAGE
        step = str(item.get("step") or "").strip()
        eligibility = item.get("eligibility") if isinstance(item.get("eligibility"), dict) else {}

        for blocked in eligibility.get("time_blocked") or []:
            if not isinstance(blocked, dict):
                continue
            pid = str(blocked.get("product_id") or "").strip()
            if pid:
                errors[pid] = ACTIVITY_TIME_REQUIREMENT_FEISHU_MESSAGE

        for blocked in eligibility.get("other_ineligible") or []:
            if not isinstance(blocked, dict):
                continue
            pid = str(blocked.get("product_id") or "").strip()
            reason = str(blocked.get("reason_text") or "不可报名").strip()
            if pid:
                if is_activity_time_requirement_text(reason):
                    errors[pid] = ACTIVITY_TIME_REQUIREMENT_FEISHU_MESSAGE
                else:
                    errors[pid] = reason

        for pid in eligibility.get("missing_ids") or []:
            pid = str(pid or "").strip()
            if pid and pid not in errors:
                errors[pid] = item_error or "商品不可报名活动"

        candidate_ids = [
            str(pid or "").strip()
            for pid in (
                list(item.get("product_ids") or [])
                + list(item.get("selected_pdd_product_ids") or [])
                + list(item.get("missing_ids") or [])
            )
            if str(pid or "").strip()
        ]
        if item_error:
            for pid in candidate_ids:
                if pid not in errors:
                    errors[pid] = item_error
        if step == "product_time_requirement_not_met":
            for pid in candidate_ids:
                errors[pid] = ACTIVITY_TIME_REQUIREMENT_FEISHU_MESSAGE

    if fallback:
        for pid in dict.fromkeys(str(x or "").strip() for x in (product_ids or []) if str(x or "").strip()):
            errors.setdefault(pid, fallback)
    return errors


def _schedule_feishu_limited_time_status(
    *,
    account_id: str,
    selected_product_ids: list[str],
    result: dict[str, Any],
    status: RunStatus,
    run_id: str = "",
) -> None:
    run_id = str(run_id or "").strip()
    claimed = _claim_feishu_terminal_log(run_id)
    if not claimed:
        logger.debug("skip duplicate feishu limited time log run_id=%s", run_id)
        return
    try:
        from pdd_agent.integrations.feishu.pdd_activity_log_sync import (
            safe_load_activity_log_product_context,
            schedule_pdd_activity_log_limited_time,
        )
        from pdd_agent.integrations.feishu.pdd_upload_sync import (
            extract_product_ids_for_limited_time_status,
            schedule_pdd_upload_limited_time_status,
        )

        product_ids = extract_product_ids_for_limited_time_status(selected_product_ids, result)
        error = _campaign_failure_message(result, status)
        account_name = _account_display_name(account_id)
        product_contexts = safe_load_activity_log_product_context(
            account_id,
            product_ids,
            account_name=account_name,
        )
        product_errors = None if status == RunStatus.SUCCESS else _extract_per_product_activity_errors(
            result,
            fallback_error=error,
            product_ids=product_ids,
        )
        schedule_pdd_upload_limited_time_status(
            account_id=account_id,
            product_ids=product_ids,
            success=status == RunStatus.SUCCESS,
            error=error,
        )
        schedule_pdd_activity_log_limited_time(
            account_id=account_id,
            product_ids=product_ids,
            success=status == RunStatus.SUCCESS,
            error=error,
            account_name=account_name,
            product_contexts=product_contexts,
            product_errors=product_errors,
        )
    except Exception:
        if run_id:
            _release_feishu_terminal_log(run_id)
        logger.exception("schedule feishu limited time status failed account=%s", account_id)


def _schedule_feishu_activity_register_status(
    *,
    account_id: str,
    activity_id: str,
    selected_product_ids: list[str],
    result: dict[str, Any],
    status: RunStatus,
    run_id: str = "",
) -> None:
    run_id = str(run_id or "").strip()
    claimed = _claim_feishu_terminal_log(run_id)
    if not claimed:
        logger.debug("skip duplicate feishu activity register log run_id=%s", run_id)
        return
    try:
        from pdd_agent.integrations.feishu.pdd_activity_log_sync import (
            safe_load_activity_log_product_context,
            schedule_pdd_activity_log_activity_register,
        )
        from pdd_agent.integrations.feishu.pdd_upload_sync import (
            extract_product_ids_from_campaign_result,
            schedule_pdd_upload_activity_register_status,
        )

        product_ids = extract_product_ids_from_campaign_result(selected_product_ids, result)
        error = _campaign_failure_message(result, status)
        account_name = _account_display_name(account_id)
        product_contexts = safe_load_activity_log_product_context(
            account_id,
            product_ids,
            account_name=account_name,
        )
        product_errors = None if status == RunStatus.SUCCESS else _extract_per_product_activity_errors(
            result,
            fallback_error=error,
            product_ids=product_ids,
        )
        schedule_pdd_upload_activity_register_status(
            account_id=account_id,
            activity_id=activity_id,
            product_ids=product_ids,
            success=status == RunStatus.SUCCESS,
            error=error,
        )
        schedule_pdd_activity_log_activity_register(
            account_id=account_id,
            activity_id=activity_id,
            product_ids=product_ids,
            success=status == RunStatus.SUCCESS,
            error=error,
            account_name=account_name,
            product_contexts=product_contexts,
            product_errors=product_errors,
        )
    except Exception:
        logger.exception(
            "schedule feishu activity register status failed account=%s activity=%s",
            account_id,
            activity_id,
        )
        if run_id:
            _release_feishu_terminal_log(run_id)


def _schedule_feishu_promotion_status(
    *,
    account_id: str,
    selected_product_ids: list[str],
    result: dict[str, Any],
    status: RunStatus,
    run_id: str = "",
) -> None:
    run_id = str(run_id or "").strip()
    claimed = _claim_feishu_terminal_log(run_id)
    if not claimed:
        logger.debug("skip duplicate feishu promotion log run_id=%s", run_id)
        return
    try:
        from pdd_agent.integrations.feishu.pdd_upload_sync import (
            extract_product_ids_from_campaign_result,
            schedule_pdd_upload_promotion_status,
        )

        product_ids = extract_product_ids_from_campaign_result(selected_product_ids, result)
        error = _summarize_traffic_message(result) if status != RunStatus.SUCCESS else ""
        schedule_pdd_upload_promotion_status(
            account_id=account_id,
            product_ids=product_ids,
            success=status == RunStatus.SUCCESS,
            error=error,
        )
    except Exception:
        if run_id:
            _release_feishu_terminal_log(run_id)
        logger.exception("schedule feishu promotion status failed account=%s", account_id)


def ensure_feishu_logged_for_terminal_run(
    *,
    run_id: str,
    agent: str = "",
    account_id: str = "",
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str = "",
    run_status: RunStatus | None = None,
    pipeline_row: Any = None,
) -> None:
    """队列/链路子任务失败或取消时兜底回写飞书（防止浏览器被关、回调丢失等漏写）。"""
    run_id = str(run_id or "").strip()
    if not run_id:
        return
    if _feishu_already_logged_for_run(run_id):
        return

    store = TaskRunStore()
    record = store.load(run_id)
    if record and record.status == RunStatus.SUCCESS:
        return

    status = run_status
    if status is None and record:
        status = record.status
    if status is None:
        status = RunStatus.FAILED
    if status == RunStatus.SUCCESS:
        return

    agent_name = str(agent or (record.agent.value if record and hasattr(record.agent, "value") else record.agent if record else "") or "").strip()
    account = str(account_id or (record.account_id if record else "") or "").strip()
    task_payload: dict[str, Any] = dict(payload or {})
    if not task_payload and run_id:
        try:
            from pdd_agent.db.repositories import get_queue_task_by_run_id

            task = get_queue_task_by_run_id(run_id)
            if task and isinstance(task.payload, dict):
                task_payload.update(task.payload)
        except Exception:
            pass

    result_payload = _normalize_terminal_failure_result(
        result if isinstance(result, dict) else (record.result if record and isinstance(record.result, dict) else {}),
        error=error or str(record.message or "") if record else error,
        run_status=status,
    )
    failed_status = RunStatus.FAILED

    try:
        if agent_name == AgentKind.LISTING.value:
            codes = list(task_payload.get("product_codes") or [])
            if pipeline_row is not None:
                codes = codes or list(getattr(pipeline_row, "product_codes", None) or [])
            _schedule_feishu_listing_result_log(
                account_id=account,
                run_id=run_id,
                result=result_payload,
                product_codes=codes,
            )
            mark_feishu_terminal_logged(run_id)
            return

        if agent_name == AgentKind.CAMPAIGN.value:
            campaign_type = str(task_payload.get("campaign_type") or "marketing_activity_register").strip()
            selected_product_ids = list(task_payload.get("pdd_product_ids") or [])
            if pipeline_row is not None:
                selected_product_ids = selected_product_ids or list(getattr(pipeline_row, "pdd_product_ids", None) or [])
            if campaign_type == "limited_time_setup":
                _schedule_feishu_limited_time_status(
                    account_id=account,
                    selected_product_ids=selected_product_ids,
                    result=result_payload,
                    status=failed_status,
                    run_id=run_id,
                )
            elif campaign_type == "marketing_activity_register":
                activity_id = str(task_payload.get("activity_id") or "").strip()
                if not activity_id and pipeline_row is not None:
                    activity_id = str(getattr(pipeline_row, "activity_id", "") or "").strip()
                _schedule_feishu_activity_register_status(
                    account_id=account,
                    activity_id=activity_id,
                    selected_product_ids=selected_product_ids,
                    result=result_payload,
                    status=failed_status,
                    run_id=run_id,
                )
            mark_feishu_terminal_logged(run_id)
            return

        if agent_name == AgentKind.TRAFFIC.value:
            traffic_type = str(task_payload.get("traffic_type") or "promotion_create").strip()
            if traffic_type != "promotion_create":
                return
            selected_product_ids = list(task_payload.get("pdd_product_ids") or [])
            if pipeline_row is not None:
                selected_product_ids = selected_product_ids or list(getattr(pipeline_row, "pdd_product_ids", None) or [])
            _schedule_feishu_promotion_status(
                account_id=account,
                selected_product_ids=selected_product_ids,
                result=result_payload,
                status=failed_status,
                run_id=run_id,
            )
            mark_feishu_terminal_logged(run_id)
    except Exception:
        logger.exception(
            "ensure feishu logged for terminal run failed run_id=%s agent=%s",
            run_id,
            agent_name,
        )


def _account_display_name(account_id: str) -> str:
    settings = load_yaml_settings()
    account = get_account_config(settings, account_id)
    if account and str(account.username or "").strip():
        return str(account.username).strip()
    return str(account_id or "").strip()


def _listing_run_timing(run_id: str) -> tuple[datetime | None, datetime | None]:
    if not run_id:
        return None, None
    try:
        record = TaskRunStore().load(run_id)
        if not record:
            return None, None
        return record.started_at, record.finished_at or datetime.now()
    except Exception:
        return None, None


def _listing_failure_row_key(
    *,
    listing_label: str = "",
    merchant_code: str = "",
    message: str = "",
) -> str:
    from pdd_agent.integrations.feishu.pdd_upload_sync import parse_listing_label_from_text

    label = str(listing_label or "").strip()
    if label:
        return label.lower()
    text = str(message or "").strip()
    if text:
        parsed_label, _ = parse_listing_label_from_text(text)
        if parsed_label:
            return parsed_label.lower()
    code = str(merchant_code or "").strip()
    if code and "/" not in code:
        return code.lower()
    if code:
        parsed_label, parsed_code = parse_listing_label_from_text(code)
        if parsed_label:
            return parsed_label.lower()
        if parsed_code:
            return parsed_code.lower()
    return text[:80].lower() if text else "unknown"


def _normalize_listing_failure_codes(
    *,
    listing_label: str = "",
    merchant_code: str = "",
    message: str = "",
    fallback_code: str = "",
) -> tuple[str, str]:
    from pdd_agent.integrations.feishu.pdd_upload_sync import parse_listing_label_from_text

    label = str(listing_label or "").strip()
    code = str(merchant_code or "").strip()
    text = str(message or "").strip()
    if not label and not code and text:
        label, code = parse_listing_label_from_text(text)
    if label and (not code or "/" in code):
        parsed_label, parsed_code = parse_listing_label_from_text(label)
        if parsed_label:
            label = parsed_label
        if parsed_code:
            code = parsed_code
    if code and "/" in code:
        _, code = parse_listing_label_from_text(code)
    if not code and label:
        _, code = parse_listing_label_from_text(label)
    if not code:
        code = fallback_code
    return label, code


def _schedule_feishu_listing_result_log(
    *,
    account_id: str,
    result: dict[str, Any],
    run_id: str = "",
    product_codes: list[str] | None = None,
) -> None:
    from pdd_agent.integrations.feishu.pdd_upload_sync import (
        map_listing_failure_record_type,
        schedule_pdd_upload_failure_log,
        schedule_pdd_upload_log,
    )

    account_name = _account_display_name(account_id)
    publish_start, publish_end = _listing_run_timing(run_id)
    duration_seconds: float | None = None
    if publish_start and publish_end:
        duration_seconds = max(0.0, (publish_end - publish_start).total_seconds())

    fallback_code = ""
    for code in product_codes or []:
        text = str(code or "").strip()
        if text:
            fallback_code = text
            break

    failures: dict[str, dict[str, Any]] = {}

    def _queue_failure(
        *,
        listing_label: str = "",
        merchant_code: str = "",
        reason_code: str = "",
        error: str = "",
        message: str = "",
        status: str = "",
        retryable: bool = False,
        legacy_status: str = "",
        priority: int = 0,
    ) -> None:
        label, code = _normalize_listing_failure_codes(
            listing_label=listing_label,
            merchant_code=merchant_code,
            message=message or error,
            fallback_code=fallback_code,
        )
        msg = str(message or error or "").strip()
        key = _listing_failure_row_key(listing_label=label, merchant_code=code, message=msg)
        existing = failures.get(key)
        if existing:
            if int(existing.get("priority") or 0) > priority:
                return
            if int(existing.get("priority") or 0) == priority and len(str(existing.get("message") or "")) >= len(msg):
                return
        failures[key] = {
            "listing_label": label,
            "merchant_code": code,
            "reason_code": reason_code,
            "error": error,
            "message": msg,
            "status": status,
            "retryable": retryable,
            "legacy_status": legacy_status,
            "priority": priority,
        }

    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        product_id = str(item.get("pdd_product_id") or "").strip()
        listing_label = str(item.get("listing_label") or "")
        merchant_code = str(
            item.get("platform_listing_code")
            or item.get("merchant_code")
            or item.get("product_code")
            or ""
        ).strip()
        is_success = status in {"success", "listed"} and bool(product_id)

        if is_success:
            item_publish_start = None
            raw_start = str(item.get("publish_submitted_at") or "").strip()
            if raw_start:
                from pdd_agent.integrations.feishu.pdd_upload_sync import _parse_created_at

                item_publish_start = _parse_created_at(raw_start)
            schedule_pdd_upload_log(
                account_id=account_id,
                listing_label=listing_label,
                title=str(item.get("title") or listing_label or ""),
                merchant_code=merchant_code,
                product_id=product_id,
                product_link=str(item.get("pdd_product_link") or ""),
                product_link_method=str(item.get("product_link_method") or ""),
                account_name=account_name,
                publish_start=item_publish_start or publish_start,
                publish_end=publish_end or datetime.now(),
                verified_at=publish_end or datetime.now(),
            )
            from pdd_agent.integrations.feishu.pdd_activity_log_sync import schedule_pdd_activity_log_seed

            schedule_pdd_activity_log_seed(
                account_id=account_id,
                product_id=product_id,
                account_name=account_name,
                seeded_at=publish_end or datetime.now(),
            )
            continue

        if status in {"failed", "retryable"} or item.get("error") or item.get("reason"):
            if item.get("feishu_failure_logged"):
                continue
            _queue_failure(
                listing_label=listing_label,
                merchant_code=merchant_code,
                reason_code=str(item.get("reason") or item.get("reason_code") or "").strip(),
                error=str(
                    item.get("error")
                    or item.get("pdd_product_capture_message")
                    or item.get("message")
                    or ""
                ).strip(),
                status=status,
                retryable=bool(item.get("retryable")),
                legacy_status=str(item.get("legacy_status") or ""),
                priority=4,
            )
            continue

        summary = str(item.get("summary") or "").strip()
        if summary:
            _queue_failure(message=summary, reason_code="no_valid_units", priority=0)

    preflight = result.get("preflight")
    issues: list[Any] = []
    if isinstance(preflight, dict):
        issues = list(preflight.get("issues") or [])
    elif preflight is not None:
        issues = list(getattr(preflight, "issues", None) or [])

    for issue in issues:
        level = str(getattr(issue, "level", None) or (issue.get("level") if isinstance(issue, dict) else "") or "")
        if level != "error":
            continue
        listing_label = str(
            getattr(issue, "listing_label", None) or (issue.get("listing_label") if isinstance(issue, dict) else "") or ""
        )
        message = str(
            getattr(issue, "message", None) or (issue.get("message") if isinstance(issue, dict) else "") or ""
        )
        if "槽位对齐" in message:
            reason_code = "slot_alignment_failed"
        elif "无有效 SKU" in message or "未解析到任何有效 SKU" in message:
            reason_code = "preflight_no_skus"
        elif "主图为空" in message or "1-5 主图" in message:
            reason_code = "preflight_no_carousel"
        elif "详情图为空" in message or "7-9 详情图" in message:
            reason_code = "preflight_no_detail"
        elif "图片" in message and ("不存在" in message or "无法" in message):
            reason_code = "image_file_missing"
        else:
            reason_code = "preflight_catalog"
        _queue_failure(
            listing_label=listing_label,
            reason_code=reason_code,
            message=message,
            retryable="槽位对齐" in message,
            priority=3,
        )

    for err in result.get("errors") or []:
        text = str(err or "").strip()
        if not text:
            continue
        reason_code = "slot_alignment_failed" if "槽位对齐" in text else "unexpected_error"
        _queue_failure(
            message=text,
            reason_code=reason_code,
            retryable="槽位对齐" in text,
            priority=2,
        )

    run_error = str(result.get("error") or "").strip()
    if run_error:
        _queue_failure(message=run_error, reason_code="unexpected_error", priority=1)

    has_unit_failures = any(int(row.get("priority") or 0) >= 2 for row in failures.values())
    for row in failures.values():
        if has_unit_failures and str(row.get("reason_code") or "") == "no_valid_units":
            continue
        schedule_pdd_upload_failure_log(
            account_id=account_id,
            account_name=account_name,
            listing_label=str(row.get("listing_label") or ""),
            merchant_code=str(row.get("merchant_code") or ""),
            record_type=map_listing_failure_record_type(
                status=str(row.get("status") or ""),
                reason_code=str(row.get("reason_code") or ""),
                retryable=bool(row.get("retryable")),
                legacy_status=str(row.get("legacy_status") or ""),
            ),
            reason_code=str(row.get("reason_code") or ""),
            error=str(row.get("error") or ""),
            message=str(row.get("message") or ""),
            publish_start=publish_start,
            publish_end=publish_end,
            duration_seconds=duration_seconds,
        )


def _activity_registration_summary_line(item: dict[str, Any]) -> str:
    """从单次活动报名结果生成一眼可读的摘要。"""
    from pdd_agent.skills.campaign.marketing_activities import ACTIVITY_TIME_REQUIREMENT_FEISHU_MESSAGE

    step = str(item.get("step") or "").strip()
    if step == "price_page_prepared":
        return "仅完成规格反查，未点击确认提交"
    if step == "product_time_requirement_not_met":
        return ACTIVITY_TIME_REQUIREMENT_FEISHU_MESSAGE
    if step == "product_not_eligible_for_activity":
        err = str(item.get("error") or "").strip()
        return err or "商品暂不可报名活动"

    product_ids = [
        str(pid).strip()
        for pid in (item.get("product_ids") or [])
        if str(pid).strip()
    ]
    selected = len(product_ids)

    finalize = item.get("finalize_result") if isinstance(item.get("finalize_result"), dict) else {}
    price_filter = finalize.get("price_filter") if isinstance(finalize.get("price_filter"), dict) else {}
    if not price_filter and isinstance(item.get("price_filter"), dict):
        price_filter = item["price_filter"]

    verify = finalize.get("submit_verification") if isinstance(finalize.get("submit_verification"), dict) else {}

    submitted = False
    if isinstance(finalize.get("confirm_submit"), dict) and finalize["confirm_submit"].get("clicked"):
        submitted = verify.get("verified") is not False
    elif step == "register_completed" and str(item.get("status") or "") == "success":
        submitted = verify.get("verified") is not False

    if str(item.get("status") or "") == "cancelled" or finalize.get("status") == "cancelled":
        return "未提交报名：全部商品不符合条件"
    if finalize.get("status") == "failed":
        err = str(finalize.get("error") or "").strip()
        if err:
            return err
        if verify.get("verified") is False:
            return "已点击确认提交，但拼多多未受理（可能仍有不合格规格）"
        return "报名未完成"
    if price_filter.get("action") == "partial_invalid_needs_manual":
        err = str(price_filter.get("error") or "").strip()
        return err.split("\n")[0] if err else "部分商品未能从活动页删除，未提交报名"
    if price_filter.get("status") == "all_products_removed":
        summary = str(price_filter.get("filter_summary") or price_filter.get("error") or "").strip()
        if summary:
            return summary.split("\n")[0]
        return "未提交报名：所选商品均含不合格规格，已整商品剔除"

    validation = price_filter.get("validation") if isinstance(price_filter.get("validation"), dict) else {}
    results = validation.get("results") if isinstance(validation.get("results"), list) else []
    passed_specs = sum(
        1
        for row in results
        if isinstance(row, dict) and row.get("valid") is True and not row.get("should_remove")
    )
    failed_specs = sum(
        1
        for row in results
        if isinstance(row, dict) and (row.get("should_remove") or row.get("valid") is False)
    )

    filter_result = price_filter.get("filter_result") if isinstance(price_filter.get("filter_result"), dict) else {}
    partial_ids = {
        str(pid).strip()
        for pid in (filter_result.get("partial_product_ids") or [])
        if str(pid).strip()
    }
    removed_ids = {
        str(pid).strip()
        for pid in (filter_result.get("removed_product_ids") or [])
        if str(pid).strip()
    }
    skipped_delete = bool(price_filter.get("action") == "partial_invalid_needs_manual")

    if submitted:
        submitted_products = 0
        blocked_products = 0
        removed_products = 0
        by_product: dict[str, list[dict[str, Any]]] = {}
        for row in results:
            if not isinstance(row, dict):
                continue
            pid = str(row.get("pdd_product_id") or row.get("page_product_id") or "").strip()
            by_product.setdefault(pid, []).append(row)

        keys = product_ids or list(by_product.keys())
        for pid in keys:
            if pid in removed_ids:
                removed_products += 1
            elif submitted:
                submitted_products += 1
            else:
                rows = by_product.get(pid, [])
                passed = sum(1 for row in rows if row.get("valid") is True and not row.get("should_remove"))
                failed = sum(1 for row in rows if row.get("should_remove") or row.get("valid") is False)
                if failed > 0 and passed == 0:
                    removed_products += 1
                elif passed > 0:
                    submitted_products += 1

        if submitted_products <= 0:
            return "未有任何商品完成报名"
        parts = [f"报名已提交：{submitted_products}/{selected or submitted_products} 个商品"]
        if blocked_products:
            parts.append(f"{blocked_products} 个待核对")
        if removed_products:
            parts.append(f"{removed_products} 个未报名")
        if failed_specs:
            parts.append(f"规格 {passed_specs}/{passed_specs + failed_specs} 合格")
        return "；".join(parts)

    if step in {"register_completed", "product_pick_confirmed"} and str(item.get("status") or "") == "success":
        return "活动任务已完成"
    return ""


def _summarize_traffic_message(result: dict[str, Any]) -> str:
    """推广任务失败时只存简短说明。"""
    top_error = str(result.get("error") or "").strip()
    if top_error:
        return top_error
    errors = result.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            text = str(item or "").strip()
            if text:
                return text
    item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
    for item in item_results:
        if str(item.get("status") or "") == "success":
            continue
        err = str(item.get("error") or "").strip()
        if err:
            step = str(item.get("step") or "").strip()
            return f"{step}: {err}" if step else err
    if item_results and all(str(r.get("status") or "") == "success" for r in item_results):
        return "推广任务已完成"
    return "推广任务失败"


def plan_tasks(message: str) -> PlanResponse:
    graph = build_orchestrator_graph()
    result = graph.invoke({"user_message": message})
    tasks = result.get("planned_tasks") or []
    return PlanResponse(
        plan_summary=result.get("plan_summary") or "",
        planned_tasks=[t.model_dump(mode="json") for t in tasks],
    )


def persist_published_item(run_id: str, account_id: str, item: dict[str, Any]) -> None:
    """单个上架成功结果写入 published_products（支持批次中途取消/中断）。"""
    if not isinstance(item, dict):
        return
    if str(item.get("status") or "") not in {"success", "listed"}:
        return
    pdd_product_id = str(item.get("pdd_product_id") or "").strip()
    if not pdd_product_id:
        return
    product_code = str(item.get("product_code") or "").strip()
    family_code = str(item.get("family_code") or "").strip()
    image_set = str(item.get("image_set") or "").strip()
    listing_label = str(item.get("listing_label") or "").strip()
    merchant_code = str(
        item.get("platform_listing_code") or item.get("merchant_code") or ""
    ).strip()
    if not product_code or not listing_label:
        return
    upsert_published_product(
        account_id=account_id,
        source_run_id=run_id,
        product_code=product_code,
        family_code=family_code,
        image_set=image_set,
        listing_label=listing_label,
        merchant_code=merchant_code,
        pdd_product_id=pdd_product_id,
        spec_metadata=item.get("spec_metadata") if isinstance(item.get("spec_metadata"), dict) else {},
    )
    try:
        from pdd_agent.api.services.listed_folder_service import record_listed_folder_from_item

        record_listed_folder_from_item(run_id, account_id, item)
    except Exception:
        logger.warning("record listed folder failed run_id=%s", run_id)


def _persist_published_products(run_id: str, account_id: str, result: dict[str, Any]) -> None:
    for item in result.get("results") or []:
        persist_published_item(run_id, account_id, item)


async def execute_listing(
    *,
    run_id: str,
    account_id: str,
    product_codes: list[str],
    dry_run: bool,
    category_keyword: str,
    platform_listing_code: str = "",
    retry_item: dict[str, Any] | None = None,
    slot_alignment_test: bool = False,
) -> dict[str, Any]:
    """执行 listing 子图，更新 RunRecord。"""
    store = TaskRunStore()
    settings = load_yaml_settings()
    account = get_account_config(settings, account_id)
    if not account:
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        _schedule_feishu_listing_result_log(
            account_id=account_id,
            run_id=run_id,
            result={"errors": [f"unknown account: {account_id}"]},
        )
        return {"error": f"unknown account: {account_id}"}

    codes = product_codes or account.product_codes
    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.PREFLIGHT)

    try:
        graph = build_listing_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "product_codes": codes,
                "platform_listing_code": platform_listing_code,
                "dry_run": dry_run,
                "category_keyword": category_keyword,
                "retry_item": retry_item or {},
                "run_id": run_id,
                "slot_alignment_test": slot_alignment_test,
            }
        )
        result = _json_safe(raw)
        # 批次内已成功的商品先落库，避免取消/中断时丢失
        _persist_published_products(run_id, account_id, result)
        record = store.load(run_id)
        if record and record.status == RunStatus.CANCELED:
            _schedule_feishu_listing_result_log(
                account_id=account_id,
                run_id=run_id,
                result=result,
                product_codes=codes,
            )
            return {"canceled": True, "results": result.get("results") or []}
        labels = []
        for u in result.get("units") or []:
            if isinstance(u, dict) and u.get("listing_label"):
                labels.append(u["listing_label"])
        for r in result.get("results") or []:
            if isinstance(r, dict) and r.get("listing_label"):
                labels.append(r["listing_label"])

        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(r.get("status") in {"failed", "retryable"} for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        _schedule_feishu_listing_result_log(
            account_id=account_id,
            run_id=run_id,
            result=result,
            product_codes=codes,
        )
        try:
            from pdd_agent.api.services.listing_failure_log import persist_listing_run_failures

            persist_listing_run_failures(
                source_run_id=run_id,
                account_id=account_id,
                result=result,
            )
        except Exception:
            logger.warning("persist listing failure details failed run_id=%s", run_id)
        store.finish(
            run_id,
            status,
            message=_summarize_listing_message(result),
            result=_compact_run_result_for_storage(result),
            listing_labels=labels,
        )
        from pdd_agent.api.services.run_cancel import clear_cancel

        clear_cancel(run_id)
        return result
    except asyncio.CancelledError:
        store.update_status(run_id, RunStatus.CANCELED, "canceled by user")
        raise
    except Exception as exc:
        logger.exception("listing job failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        _schedule_feishu_listing_result_log(
            account_id=account_id,
            run_id=run_id,
            result={"errors": [str(exc)], "results": [{"status": "failed", "reason": "unexpected_error", "error": str(exc)}]},
            product_codes=codes,
        )
        return {"error": str(exc)}


def create_listing_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.LISTING, account_id).run_id


def _sync_single_delist_result(result: dict[str, Any]) -> None:
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        mapping_id = str(item.get("mapping_id") or "").strip()
        if not mapping_id:
            continue
        if item.get("status") == "delisted" and not item.get("error"):
            update_published_product_status(mapping_id, "delisted")


async def execute_delist(
    *,
    run_id: str,
    account_id: str,
    dry_run: bool | None = None,
    delist_params: dict | None = None,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    params = delist_params or {}
    if dry_run is not None:
        params["dry_run"] = dry_run

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    try:
        graph = build_delist_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "dry_run": params.get("dry_run", settings.delist.dry_run),
                "delist_params": params,
            }
        )
        result = _json_safe(raw)
        status = RunStatus.SUCCESS if not result.get("errors") else RunStatus.FAILED
        if status == RunStatus.SUCCESS:
            _sync_single_delist_result(result)
        store.finish(
            run_id,
            status,
            message=_summarize_delist_message(result),
            result=_compact_run_result_for_storage(result),
        )
        return result
    except asyncio.CancelledError:
        store.update_status(run_id, RunStatus.CANCELED, "canceled by user")
        raise
    except Exception as exc:
        logger.exception("delist job failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


def create_delist_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.DELIST, account_id).run_id


def create_published_goods_lookup_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.LISTING, account_id).run_id


async def execute_published_goods_lookup(
    *,
    run_id: str,
    account_id: str,
    mapping_id: str,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    account = get_account_config(settings, account_id)
    if not account:
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    row = get_published_product_by_mapping_id(mapping_id)
    if not row:
        store.finish(run_id, RunStatus.FAILED, f"published product not found: {mapping_id}")
        return {"error": f"published product not found: {mapping_id}"}
    if not row.pdd_product_id:
        store.finish(run_id, RunStatus.FAILED, "published product has no pdd_product_id")
        return {"error": "published product has no pdd_product_id"}

    store.update_status(run_id, RunStatus.RUNNING, "published goods lookup")
    store.update_phase(run_id, TaskPhase.BROWSER)
    pdd_product_id = str(row.pdd_product_id).strip()

    def _job(dp):
        return lookup_published_product_in_goods_list(dp, account_id, pdd_product_id)

    try:
        result = await run_browser_job_async(settings, account, _job)
        lookup_payload = result.get("pdd_goods_lookup")
        if isinstance(lookup_payload, dict):
            patch_published_product_spec_metadata(mapping_id, {"pdd_goods_lookup": lookup_payload})

        if str(result.get("status") or "") == "success":
            store.finish(
                run_id,
                RunStatus.SUCCESS,
                message=str(result.get("message") or f"goods lookup ok product_id={pdd_product_id}"),
                result=_json_safe(result),
            )
            return result

        error = str(result.get("error") or "published goods lookup failed")
        store.finish(run_id, RunStatus.FAILED, error, result=_json_safe(result))
        return result
    except Exception as exc:
        logger.exception("published goods lookup failed run_id=%s mapping_id=%s", run_id, mapping_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


async def execute_campaign_marketing_activity_register(
    *,
    run_id: str,
    account_id: str,
    activity_id: str,
    pdd_product_ids: list[str] | None = None,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    activity_id = str(activity_id or "").strip()
    selected_product_ids = list(dict.fromkeys(pdd_product_ids or []))
    if not get_account_config(settings, account_id):
        err = f"unknown account: {account_id}"
        failed_result = {"error": err}
        store.finish(run_id, RunStatus.FAILED, err)
        _schedule_feishu_activity_register_status(
            account_id=account_id,
            activity_id=activity_id,
            selected_product_ids=selected_product_ids,
            result=failed_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        return {"error": err}
    if not activity_id:
        err = "activity_id is required"
        failed_result = {"error": err}
        store.finish(run_id, RunStatus.FAILED, err)
        _schedule_feishu_activity_register_status(
            account_id=account_id,
            activity_id=activity_id,
            selected_product_ids=selected_product_ids,
            result=failed_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        return {"error": err}
    if not selected_product_ids:
        err = "pdd_product_ids is required"
        failed_result = {"error": err}
        store.finish(run_id, RunStatus.FAILED, err)
        _schedule_feishu_activity_register_status(
            account_id=account_id,
            activity_id=activity_id,
            selected_product_ids=selected_product_ids,
            result=failed_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        return {"error": err}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    try:
        graph = build_campaign_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "campaign_type": "marketing_activity_register",
                "marketing_activity_id": activity_id,
                "pdd_product_ids": selected_product_ids,
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(str(r.get("status") or "") != "success" for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        store.finish(run_id, status, message=_summarize_campaign_message(result), result=result)
        _schedule_feishu_activity_register_status(
            account_id=account_id,
            activity_id=activity_id,
            selected_product_ids=selected_product_ids,
            result=result,
            status=status,
            run_id=run_id,
        )
        return result
    except asyncio.CancelledError:
        canceled_result = _normalize_terminal_failure_result(
            {},
            error="canceled by user",
            run_status=RunStatus.CANCELED,
        )
        store.update_status(run_id, RunStatus.CANCELED, "canceled by user")
        _schedule_feishu_activity_register_status(
            account_id=account_id,
            activity_id=activity_id,
            selected_product_ids=selected_product_ids,
            result=canceled_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        raise
    except Exception as exc:
        logger.exception("campaign marketing activity register failed run_id=%s", run_id)
        failed_result = {"error": str(exc)}
        store.finish(run_id, RunStatus.FAILED, str(exc), result=failed_result)
        _schedule_feishu_activity_register_status(
            account_id=account_id,
            activity_id=activity_id,
            selected_product_ids=selected_product_ids,
            result=failed_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        return {"error": str(exc)}


async def execute_campaign_marketing_activity_search(
    *,
    run_id: str,
    account_id: str,
    activity_id: str,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    activity_id = str(activity_id or "").strip()
    if not activity_id:
        store.finish(run_id, RunStatus.FAILED, "activity_id is required")
        return {"error": "activity_id is required"}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    try:
        graph = build_campaign_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "campaign_type": "marketing_activity_search",
                "marketing_activity_id": activity_id,
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(str(r.get("status") or "") != "success" for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        store.finish(run_id, status, message=_summarize_campaign_message(result), result=result)
        return result
    except Exception as exc:
        logger.exception("campaign marketing activity search failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


async def execute_campaign_limited_time_setup(
    *,
    run_id: str,
    account_id: str,
    pdd_product_ids: list[str] | None = None,
    published_mapping_ids: list[str] | None = None,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    selected_product_ids = list(dict.fromkeys((pdd_product_ids or [])))
    selected_mapping_ids = list(dict.fromkeys((published_mapping_ids or [])))
    if not get_account_config(settings, account_id):
        err = f"unknown account: {account_id}"
        failed_result = {"error": err}
        store.finish(run_id, RunStatus.FAILED, err)
        _schedule_feishu_limited_time_status(
            account_id=account_id,
            selected_product_ids=selected_product_ids,
            result=failed_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        return {"error": err}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    try:
        graph = build_campaign_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "campaign_type": "limited_time_setup",
                "pdd_product_ids": selected_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(str(r.get("status") or "") != "success" for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        store.finish(run_id, status, message=_summarize_campaign_message(result), result=result)
        _schedule_feishu_limited_time_status(
            account_id=account_id,
            selected_product_ids=selected_product_ids,
            result=result,
            status=status,
            run_id=run_id,
        )
        return result
    except asyncio.CancelledError:
        canceled_result = _normalize_terminal_failure_result(
            {},
            error="canceled by user",
            run_status=RunStatus.CANCELED,
        )
        store.update_status(run_id, RunStatus.CANCELED, "canceled by user")
        _schedule_feishu_limited_time_status(
            account_id=account_id,
            selected_product_ids=selected_product_ids,
            result=canceled_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        raise
    except Exception as exc:
        logger.exception("campaign job failed run_id=%s", run_id)
        failed_result = {"error": str(exc)}
        store.finish(run_id, RunStatus.FAILED, str(exc), result=failed_result)
        _schedule_feishu_limited_time_status(
            account_id=account_id,
            selected_product_ids=selected_product_ids,
            result=failed_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        return {"error": str(exc)}


def create_campaign_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.CAMPAIGN, account_id).run_id


async def execute_traffic_promotion_create(
    *,
    run_id: str,
    account_id: str,
    pdd_product_ids: list[str] | None = None,
    published_mapping_ids: list[str] | None = None,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    selected_product_ids = list(dict.fromkeys(pdd_product_ids or []))
    selected_mapping_ids = list(dict.fromkeys(published_mapping_ids or []))
    try:
        graph = build_traffic_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "traffic_type": "promotion_create",
                "pdd_product_ids": selected_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(str(r.get("status") or "") != "success" for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        store.finish(run_id, status, message=_summarize_traffic_message(result), result=result)
        _schedule_feishu_promotion_status(
            account_id=account_id,
            selected_product_ids=selected_product_ids,
            result=result,
            status=status,
            run_id=run_id,
        )
        return result
    except asyncio.CancelledError:
        canceled_result = _normalize_terminal_failure_result(
            {},
            error="canceled by user",
            run_status=RunStatus.CANCELED,
        )
        store.update_status(run_id, RunStatus.CANCELED, "canceled by user")
        _schedule_feishu_promotion_status(
            account_id=account_id,
            selected_product_ids=selected_product_ids,
            result=canceled_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        raise
    except Exception as exc:
        logger.exception("traffic promotion create failed run_id=%s", run_id)
        failed_result = {"error": str(exc)}
        store.finish(run_id, RunStatus.FAILED, str(exc), result=failed_result)
        _schedule_feishu_promotion_status(
            account_id=account_id,
            selected_product_ids=selected_product_ids,
            result=failed_result,
            status=RunStatus.FAILED,
            run_id=run_id,
        )
        return {"error": str(exc)}


async def execute_traffic_promotion_report_scrape(
    *,
    run_id: str,
    account_id: str,
) -> dict[str, Any]:
    """抓取稳定成本推广昨日数据并回写飞书。"""
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    try:
        graph = build_traffic_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "traffic_type": "promotion_report_scrape",
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        scrape_result = item_results[0] if item_results else {}
        success = (
            not result.get("errors")
            and str(scrape_result.get("status") or "") == "success"
        )
        status = RunStatus.SUCCESS if success else RunStatus.FAILED

        from pdd_agent.integrations.feishu.traffic_report_sync import (
            format_traffic_scrape_failure_reason,
            sync_traffic_report_to_feishu,
        )

        if success:
            feishu_result = sync_traffic_report_to_feishu(
                account_id=account_id,
                rows=list(scrape_result.get("rows") or []),
                report_date=str(scrape_result.get("report_date") or ""),
            )
            scrape_result["feishu_sync"] = feishu_result
            if feishu_result.get("failed"):
                status = RunStatus.FAILED
                result.setdefault("errors", []).append(
                    str(feishu_result.get("message") or "feishu sync failed")
                )
            created = len(feishu_result.get("created_record_ids") or [])
            updated = len(feishu_result.get("updated_record_ids") or [])
            print(
                f"[{account_id}] 飞书投流回写：新增{created}条、更新{updated}条",
                flush=True,
            )
        else:
            fail_msg = str(
                scrape_result.get("message")
                or scrape_result.get("error")
                or "投流数据抓取失败"
            ).strip()
            print(f"[{account_id}] 投流抓取失败，跳过飞书写入：{fail_msg}", flush=True)
            sync_traffic_report_to_feishu(
                account_id=account_id,
                rows=[],
                report_date=str(scrape_result.get("report_date") or ""),
                error=format_traffic_scrape_failure_reason(scrape_result),
            )

        result["results"] = item_results
        message = _summarize_traffic_report_message(result, scrape_result)
        store.finish(run_id, status, message=message, result=result)
        return result
    except Exception as exc:
        logger.exception("traffic promotion report scrape failed run_id=%s", run_id)
        failed_result = {"error": str(exc)}
        store.finish(run_id, RunStatus.FAILED, str(exc), result=failed_result)
        return {"error": str(exc)}


def _summarize_traffic_report_message(result: dict[str, Any], scrape_result: dict[str, Any]) -> str:
    if result.get("errors"):
        for item in result.get("errors") or []:
            text = str(item or "").strip()
            if text:
                return _truncate_db_text(text, _DB_MESSAGE_MAX)
    total = int(scrape_result.get("total") or 0)
    feishu = scrape_result.get("feishu_sync") if isinstance(scrape_result.get("feishu_sync"), dict) else {}
    created = len(feishu.get("created_record_ids") or [])
    updated = len(feishu.get("updated_record_ids") or [])
    report_date = str(scrape_result.get("report_date") or "")
    return _truncate_db_text(
        f"投流昨日数据抓取完成：{total}条；飞书新增{created}条、更新{updated}条；日期={report_date}",
        _DB_MESSAGE_MAX,
    )


def create_traffic_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.TRAFFIC, account_id).run_id

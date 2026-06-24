"""上架 → 限时限量购 → 活动 → 推广 整合链路。"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from pdd_agent.api.services.task_runner import create_campaign_run, create_listing_run, create_traffic_run
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    create_integrated_pipeline,
    enqueue_task,
    get_integrated_pipeline,
    count_integrated_pipelines,
    get_published_product,
    list_integrated_pipelines,
    update_integrated_pipeline,
)
from pdd_agent.domain.enums import AgentKind, RunStatus
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)

ListingInputMode = Literal["selector", "cycle_relist"]


def _resolve_pipeline_listing_codes(
    product_codes: list[str],
    *,
    listing_input_mode: ListingInputMode = "selector",
) -> tuple[list[str], dict[str, Any]]:
    """整合链路上架入参：页面/RabbitMQ 用 selector；循环上架用 cycle_relist 解析。"""
    raw_codes = list(dict.fromkeys(str(code).strip() for code in product_codes if str(code).strip()))
    if not raw_codes:
        raise ValueError("product_codes is required")

    if listing_input_mode == "selector":
        return raw_codes, {"listing_input_mode": "selector", "listing_input_codes": raw_codes}

    from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve import (
        resolve_cycle_relist_listing_selectors,
    )

    selectors, details = resolve_cycle_relist_listing_selectors(raw_codes)
    return selectors, {
        "listing_input_mode": "cycle_relist",
        "listing_input_codes": raw_codes,
        "cycle_relist_resolve": details,
    }

DEMO_ACTIVITY_DELAY_MINUTES = 2
DEMO_ACTIVITY_JITTER_MAX_SECONDS = 60
# 上架刚结束立即开浏览器易抢 profile / 页面未稳定，限时限量购稍延后
LIMITED_TIME_POST_LISTING_DELAY_SECONDS = 5

TERMINAL_PIPELINE_STATUSES = frozenset({"completed", "failed", "canceled"})
CAMPAIGN_TIME_REQUIREMENT_STEP = "product_time_requirement_not_met"
CAMPAIGN_NOT_ELIGIBLE_STEP = "product_not_eligible_for_activity"
CAMPAIGN_SKIP_TRAFFIC_STEPS = frozenset(
    {CAMPAIGN_TIME_REQUIREMENT_STEP, CAMPAIGN_NOT_ELIGIBLE_STEP}
)
CAMPAIGN_SKIP_TRAFFIC_OUTCOMES = frozenset(
    {"time_requirement_not_met", "not_eligible_for_activity", "activity_registration_skipped"}
)


def _try_wecom_pipeline_failed(row, *, error: str, current_step: str) -> None:
    try:
        from pdd_agent.integrations.wecom.notify import notify_pipeline_failed

        notify_pipeline_failed(
            account_id=str(row.account_id or ""),
            pipeline_id=str(row.pipeline_id or ""),
            product_codes=list(row.product_codes or []),
            error=error,
            current_step=current_step,
        )
    except Exception:
        logger.warning("wecom pipeline notify failed pipeline_id=%s", row.pipeline_id, exc_info=True)


def _batch_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def resolve_batch_concurrency(requested: int | None) -> int:
    configured = load_yaml_settings().batch.max_concurrent_stores
    value = requested or configured or 3
    return max(1, min(5, value))


def resolve_batch_delay(min_requested: int | None, max_requested: int | None) -> tuple[int, int]:
    batch = load_yaml_settings().batch
    min_seconds = (
        min_requested if min_requested is not None else batch.store_start_delay_min_seconds
    )
    max_seconds = (
        max_requested if max_requested is not None else batch.store_start_delay_max_seconds
    )
    min_seconds = max(0, min(3600, min_seconds))
    max_seconds = max(0, min(3600, max_seconds))
    if max_seconds < min_seconds:
        max_seconds = min_seconds
    return min_seconds, max_seconds


def _pipeline_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _resolve_activity_delay(*, demo_mode: bool, activity_delay_hours: float) -> timedelta:
    if demo_mode:
        return timedelta(minutes=DEMO_ACTIVITY_DELAY_MINUTES)
    hours = max(0.0, float(activity_delay_hours or 24.0))
    return timedelta(hours=hours)


def _activity_jitter_max_seconds(*, demo_mode: bool) -> int:
    batch = load_yaml_settings().batch
    if demo_mode:
        return min(DEMO_ACTIVITY_JITTER_MAX_SECONDS, batch.activity_schedule_jitter_max_seconds)
    return max(0, int(batch.activity_schedule_jitter_max_seconds or 0))


def resolve_activity_scheduled_at(
    *,
    demo_mode: bool,
    activity_delay_hours: float,
    jitter_max_seconds: int | None = None,
) -> datetime:
    """上架完成后预约活动的时间；正式模式在基础延迟上叠加随机抖动，避免集体到期。"""
    base = datetime.now() + _resolve_activity_delay(
        demo_mode=demo_mode,
        activity_delay_hours=activity_delay_hours,
    )
    jitter_cap = (
        jitter_max_seconds
        if jitter_max_seconds is not None
        else _activity_jitter_max_seconds(demo_mode=demo_mode)
    )
    if jitter_cap > 0:
        base += timedelta(seconds=random.randint(0, jitter_cap))
    return base


def _extract_listing_products(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    pdd_ids: list[str] = []
    mapping_ids: list[str] = []
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") not in {"success", "completed", "listed"}:
            continue
        pid = str(item.get("pdd_product_id") or "").strip()
        if pid:
            pdd_ids.append(pid)
        mapping_id = str(item.get("mapping_id") or "").strip()
        if mapping_id:
            mapping_ids.append(mapping_id)
    return list(dict.fromkeys(pdd_ids)), list(dict.fromkeys(mapping_ids))


def _campaign_result_items(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    bucket = (result or {}).get("results")
    if not isinstance(bucket, list):
        return items
    for item in bucket:
        if isinstance(item, dict):
            items.append(item)
    return items


def _normalize_campaign_error(error: str | list | None) -> str:
    if isinstance(error, list):
        return "; ".join(str(item).strip() for item in error if str(item).strip())
    return str(error or "").strip()


def _should_skip_campaign_for_traffic(result: dict[str, Any] | None, error: str | list | None = "") -> bool:
    """整合链路：商品暂不可报名活动时跳过活动步骤，继续推广。"""
    for item in _campaign_result_items(result):
        if str(item.get("step") or "") in CAMPAIGN_SKIP_TRAFFIC_STEPS:
            return True
    text = _normalize_campaign_error(error)
    return any(
        marker in text
        for marker in (
            "未满足时间要求",
            "需等待1天",
            "等待1天",
            "1天后再试",
            "商品需过24h后才可以报活动",
            "24h后才可以报活动",
            "部分商品不可报名活动",
            "不可报名活动",
        )
    )


def _campaign_skip_outcome(result: dict[str, Any] | None) -> str:
    for item in _campaign_result_items(result):
        step = str(item.get("step") or "")
        if step == CAMPAIGN_TIME_REQUIREMENT_STEP:
            return "time_requirement_not_met"
        if step == CAMPAIGN_NOT_ELIGIBLE_STEP:
            return "not_eligible_for_activity"
    return "activity_registration_skipped"


def _campaign_skip_message(result: dict[str, Any] | None, error: str | list | None = "") -> str:
    for item in _campaign_result_items(result):
        if str(item.get("step") or "") in CAMPAIGN_SKIP_TRAFFIC_STEPS:
            return str(item.get("error") or _normalize_campaign_error(error) or "活动报名未成功").strip()
    text = _normalize_campaign_error(error)
    if text:
        return text
    return "商品暂不可报名活动，已跳过活动继续推广"


def _is_campaign_time_requirement_failure(result: dict[str, Any] | None, error: str = "") -> bool:
    return _should_skip_campaign_for_traffic(result, error)


def _campaign_time_requirement_message(result: dict[str, Any] | None, error: str = "") -> str:
    return _campaign_skip_message(result, error)


def _normalize_pipeline_activity_ids(activity_id: str = "", activity_ids: list[str] | None = None) -> list[str]:
    ids = [str(item).strip() for item in (activity_ids or []) if str(item).strip()]
    if ids:
        return list(dict.fromkeys(ids))
    legacy = str(activity_id or "").strip()
    return [legacy] if legacy else []


def _pipeline_activity_ids(row) -> list[str]:
    meta = dict(row.meta or {})
    ids = meta.get("activity_ids")
    if isinstance(ids, list):
        normalized = [str(item).strip() for item in ids if str(item).strip()]
        if normalized:
            return list(dict.fromkeys(normalized))
    activity_id = str(row.activity_id or "").strip()
    return [activity_id] if activity_id else []


def _campaign_activity_index(row) -> int:
    return max(0, int((row.meta or {}).get("campaign_activity_index") or 0))


def _campaign_results(row) -> list[dict[str, Any]]:
    raw = (row.meta or {}).get("campaign_results")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _campaign_run_already_handled(row, run_id: str) -> bool:
    run_id = str(run_id or "").strip()
    if not run_id:
        return False
    handled = (row.meta or {}).get("handled_campaign_run_ids")
    if isinstance(handled, list) and run_id in handled:
        return True
    return any(str(item.get("run_id") or "").strip() == run_id for item in _campaign_results(row))


def _mark_campaign_run_handled(meta_patch: dict[str, Any], run_id: str) -> None:
    run_id = str(run_id or "").strip()
    if not run_id:
        return
    handled = [
        str(item).strip()
        for item in (meta_patch.get("handled_campaign_run_ids") or [])
        if str(item).strip()
    ]
    if run_id not in handled:
        handled.append(run_id)
    meta_patch["handled_campaign_run_ids"] = handled


def _traffic_run_is_live(run_id: str) -> bool:
    run_id = str(run_id or "").strip()
    if not run_id:
        return False
    record = TaskRunStore().load(run_id)
    if not record:
        return False
    status = _run_status_value(record.status)
    return status in {
        RunStatus.PENDING.value,
        RunStatus.RUNNING.value,
        RunStatus.SUCCESS.value,
        "pending",
        "running",
        "success",
    }


def _pipeline_traffic_already_enqueued(row) -> bool:
    meta = row.meta if isinstance(row.meta, dict) else {}
    if bool(meta.get("traffic_enqueued")):
        return True
    return _traffic_run_is_live(str(row.traffic_run_id or ""))


def _append_campaign_result(
    meta_patch: dict[str, Any],
    row,
    *,
    activity_id: str,
    run_id: str,
    success: bool,
    skipped: bool,
    error: str,
    summary: str,
) -> None:
    run_id = str(run_id or "").strip()
    results = list(_campaign_results(row))
    if run_id and any(str(item.get("run_id") or "").strip() == run_id for item in results):
        meta_patch["campaign_results"] = results
        return
    results.append(
        {
            "activity_id": activity_id,
            "run_id": run_id,
            "success": bool(success),
            "skipped": bool(skipped),
            "error": str(error or ""),
            "summary": str(summary or ""),
        }
    )
    meta_patch["campaign_results"] = results


def _pipeline_auto_limited_time(row) -> bool:
    """选了活动报名时，限时限量购为必跑步骤。"""
    return bool(_pipeline_activity_ids(row))


def _pipeline_continue_after_limited_time_failure(row) -> bool:
    """限时限量购失败后仍继续活动报名与推广。"""
    return bool((row.meta or {}).get("continue_after_limited_time_failure"))


def _pipeline_continue_after_activity_failure(row) -> bool:
    """活动报名失败后仍继续下一个活动，并在全部处理完后继续推广。"""
    return bool((row.meta or {}).get("continue_after_activity_failure"))


def _limited_time_completed(row) -> bool:
    run_id = _pipeline_limited_time_run_id(row)
    if not run_id:
        return False
    record = TaskRunStore().load(run_id)
    if not record:
        return False
    status = str(record.status.value if hasattr(record.status, "value") else record.status)
    return status in {"success", "completed"}


def _pipeline_limited_time_run_id(row) -> str:
    return str((row.meta or {}).get("limited_time_run_id") or "").strip()


def _schedule_pipeline_campaign(
    row,
    *,
    activity_index: int,
    scheduled_at: datetime,
    pdd_ids: list[str] | None = None,
    mapping_ids: list[str] | None = None,
    meta_patch: dict[str, Any] | None = None,
) -> str:
    activity_ids = _pipeline_activity_ids(row)
    if activity_index < 0 or activity_index >= len(activity_ids):
        raise ValueError("activity_index out of range")
    activity_id = activity_ids[activity_index]
    campaign_run_id = create_campaign_run(row.account_id)
    resolved_pdd_ids = list(pdd_ids if pdd_ids is not None else (row.pdd_product_ids or []))
    enqueue_task(
        agent=AgentKind.CAMPAIGN.value,
        run_id=campaign_run_id,
        account_id=row.account_id,
        payload={
            "pipeline_id": row.pipeline_id,
            "campaign_type": "marketing_activity_register",
            "activity_id": activity_id,
            "pdd_product_ids": resolved_pdd_ids,
        },
        scheduled_at=scheduled_at,
    )
    patch = dict(meta_patch or {})
    patch["campaign_activity_index"] = activity_index
    is_future = scheduled_at > datetime.now()
    update_integrated_pipeline(
        row.pipeline_id,
        status="waiting_activity" if is_future else "running",
        current_step="waiting_activity" if is_future else "campaign_queued",
        pdd_product_ids=resolved_pdd_ids if pdd_ids is not None else None,
        mapping_ids=list(mapping_ids) if mapping_ids is not None else None,
        campaign_run_id=campaign_run_id,
        scheduled_activity_at=scheduled_at,
        error="",
        meta_patch=patch,
    )
    return campaign_run_id


def _enqueue_pipeline_limited_time(
    row,
    *,
    pdd_ids: list[str] | None = None,
    mapping_ids: list[str] | None = None,
    meta_patch: dict[str, Any] | None = None,
    scheduled_at: datetime | None = None,
) -> None:
    resolved_pdd_ids = list(pdd_ids if pdd_ids is not None else (row.pdd_product_ids or []))
    resolved_mapping_ids = list(mapping_ids if mapping_ids is not None else (row.mapping_ids or []))
    limited_time_run_id = create_campaign_run(row.account_id)
    run_at = scheduled_at or datetime.now()
    enqueue_task(
        agent=AgentKind.CAMPAIGN.value,
        run_id=limited_time_run_id,
        account_id=row.account_id,
        payload={
            "pipeline_id": row.pipeline_id,
            "campaign_type": "limited_time_setup",
            "pdd_product_ids": resolved_pdd_ids,
            "published_mapping_ids": resolved_mapping_ids,
        },
        scheduled_at=run_at,
    )
    patch = dict(meta_patch or {})
    patch["limited_time_run_id"] = limited_time_run_id
    is_future = run_at > datetime.now()
    update_integrated_pipeline(
        row.pipeline_id,
        status="waiting_limited_time" if is_future else "running",
        current_step="waiting_limited_time" if is_future else "limited_time_queued",
        pdd_product_ids=resolved_pdd_ids if pdd_ids is not None else None,
        mapping_ids=resolved_mapping_ids if mapping_ids is not None else None,
        error="",
        meta_patch=patch,
    )


def _schedule_pipeline_activity_after_limited_time(
    row,
    *,
    meta_patch: dict[str, Any] | None = None,
) -> None:
    scheduled_at = resolve_activity_scheduled_at(
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )
    base_at = datetime.now() + _resolve_activity_delay(
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )
    activity_jitter_seconds = max(0, int((scheduled_at - base_at).total_seconds()))
    patch = dict(meta_patch or {})
    patch["activity_jitter_seconds"] = activity_jitter_seconds
    _schedule_pipeline_campaign(
        row,
        activity_index=0,
        scheduled_at=scheduled_at,
        meta_patch=patch,
    )
    logger.info(
        "pipeline %s limited time done, activity scheduled at %s activities=%s",
        row.pipeline_id,
        scheduled_at,
        _pipeline_activity_ids(row),
    )


def _enqueue_pipeline_traffic(row, *, meta_patch: dict[str, Any] | None = None) -> None:
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    if _pipeline_traffic_already_enqueued(refreshed):
        logger.info(
            "skip duplicate traffic enqueue pipeline=%s traffic_run_id=%s",
            refreshed.pipeline_id,
            refreshed.traffic_run_id,
        )
        return
    pdd_ids = list(refreshed.pdd_product_ids or [])
    mapping_ids = list(refreshed.mapping_ids or [])
    traffic_run_id = create_traffic_run(refreshed.account_id)
    enqueue_task(
        agent=AgentKind.TRAFFIC.value,
        run_id=traffic_run_id,
        account_id=refreshed.account_id,
        payload={
            "pipeline_id": refreshed.pipeline_id,
            "traffic_type": "promotion_create",
            "pdd_product_ids": pdd_ids,
            "published_mapping_ids": mapping_ids,
        },
        scheduled_at=datetime.now(),
    )
    patch = dict(meta_patch or {})
    patch["traffic_enqueued"] = True
    update_integrated_pipeline(
        refreshed.pipeline_id,
        status="running",
        current_step="traffic_queued",
        traffic_run_id=traffic_run_id,
        error="",
        meta_patch=patch,
    )


LISTING_SKIPPED_OUTCOME = "skipped_already_listed"
LISTING_PARTIAL_OUTCOME = "partial_listing_failure"

LISTING_UNIT_STATUS_LABELS: dict[str, str] = {
    "skipped": "已跳过",
    "preflight_failed": "校验未通过",
    "ready": "可上架",
    "pending": "等待中",
    "listing": "上架中",
    "success": "已上架",
    "failed": "上架失败",
    "canceled": "未执行",
}


def _selector_to_listing_label(selector: str) -> str:
    from pdd_agent.skills.listing.catalog import _parse_listing_target_product_selector

    text = str(selector or "").strip()
    parsed = _parse_listing_target_product_selector(text)
    if parsed:
        _family, image_set, product_code = parsed
        return f"{product_code}/{image_set}" if image_set else product_code
    parts = [part.strip() for part in text.split("/") if part.strip()]
    if len(parts) >= 3:
        return f"{parts[-1]}/{parts[-2]}"
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    return text


def _issue_field(issue: Any, name: str) -> str:
    if isinstance(issue, dict):
        return str(issue.get(name) or "").strip()
    return str(getattr(issue, name, "") or "").strip()


def _unit_label(unit: Any) -> str:
    if isinstance(unit, dict):
        product_code = str(unit.get("product_code") or "").strip()
        image_set = str(unit.get("image_set") or "").strip()
        if image_set:
            return f"{product_code}/{image_set}"
        return product_code
    product_code = str(getattr(unit, "product_code", "") or "").strip()
    image_set = str(getattr(unit, "image_set", "") or "").strip()
    if image_set:
        return f"{product_code}/{image_set}"
    return product_code


def _parse_preflight_snapshot(result: dict[str, Any]) -> tuple[dict[str, str], set[str]]:
    """返回 (error_label->reason_code, valid_labels)。"""
    preflight_raw = result.get("preflight")
    if not preflight_raw:
        return {}, set()

    if isinstance(preflight_raw, dict):
        issues = list(preflight_raw.get("issues") or [])
        units = list(preflight_raw.get("units") or [])
    else:
        issues = list(getattr(preflight_raw, "issues", None) or [])
        units = list(getattr(preflight_raw, "units", None) or [])

    errors: dict[str, str] = {}
    for issue in issues:
        if _issue_field(issue, "level") != "error":
            continue
        label = _issue_field(issue, "listing_label") or _issue_field(issue, "message")
        if not label:
            continue
        reason = _issue_field(issue, "reason_code") or "preflight_catalog"
        errors[label] = reason

    valid: set[str] = set()
    for unit in units:
        label = _unit_label(unit)
        if label and label not in errors:
            valid.add(label)
    return errors, valid


def build_listing_unit_statuses(row) -> list[dict[str, Any]]:
    """整合链路：按套图汇总可上架/失败/进行中等状态，供前端展示。"""
    if row is None:
        return []

    meta = dict(row.meta or {})
    skip_selectors = {
        str(item).strip() for item in (meta.get("listing_skip_selectors") or []) if str(item).strip()
    }
    selectors = [str(item).strip() for item in (row.product_codes or []) if str(item).strip()]
    if not selectors:
        return []

    preflight_errors: dict[str, str] = {}
    valid_labels: set[str] = set()
    result_by_label: dict[str, dict[str, Any]] = {}
    run_status = ""
    run_phase = ""

    if row.listing_run_id:
        record = TaskRunStore().load(row.listing_run_id)
        if record:
            run_status = str(
                record.status.value if hasattr(record.status, "value") else record.status
            )
            run_phase = str(record.phase.value if hasattr(record.phase, "value") else record.phase)
            result = dict(record.result or {})
            preflight_errors, valid_labels = _parse_preflight_snapshot(result)
            for item in result.get("results") or []:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("listing_label") or "").strip()
                if label:
                    result_by_label[label] = item

    for label in meta.get("listing_failed_labels") or []:
        text = str(label or "").strip()
        if text:
            preflight_errors.setdefault(text, "preflight_catalog")

    statuses: list[dict[str, Any]] = []
    for selector in selectors:
        label = _selector_to_listing_label(selector)
        reason_code = ""
        if selector in skip_selectors:
            status = "skipped"
            reason_code = "skipped_already_listed"
        elif label in result_by_label:
            item = result_by_label[label]
            item_status = str(item.get("status") or "").strip().lower()
            product_id = str(item.get("pdd_product_id") or "").strip()
            if item_status in {"success", "listed"} and bool(product_id or item_status == "listed"):
                status = "success"
            else:
                status = "failed"
                reason_code = str(item.get("reason") or item.get("reason_code") or "listing_failed").strip()
        elif label in preflight_errors:
            status = "preflight_failed"
            reason_code = preflight_errors[label]
        elif label in valid_labels:
            if run_status == RunStatus.RUNNING.value:
                status = "listing"
            elif run_status == RunStatus.CANCELED.value:
                status = "canceled"
            else:
                status = "ready"
        elif run_status in {RunStatus.RUNNING.value, ""} and not preflight_errors:
            status = "pending"
        else:
            status = "pending"

        statuses.append(
            {
                "selector": selector,
                "listing_label": label,
                "status": status,
                "status_label": LISTING_UNIT_STATUS_LABELS.get(status, status),
                "reason_code": reason_code,
            }
        )
    return statuses


def _parse_pipeline_product_selector(selector: str) -> tuple[str, str, str]:
    """解析 BD713/第一套图/BD713A → (family, image_set, product_code)。"""
    parts = [part.strip() for part in str(selector or "").split("/") if part.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    if len(parts) == 1:
        return "", "", parts[0]
    return "", "", ""


def resolve_published_products_for_pipeline(
    account_id: str,
    selectors: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """将整合链路商品选择解析为在售拼多多 ID；返回 (pdd_ids, mapping_ids, missing_selectors)。"""
    account_id = str(account_id or "").strip()
    pdd_ids: list[str] = []
    mapping_ids: list[str] = []
    missing: list[str] = []
    for selector in selectors:
        selector = str(selector or "").strip()
        if not selector:
            continue
        _family, image_set, product_code = _parse_pipeline_product_selector(selector)
        if not product_code:
            missing.append(selector)
            continue
        row = get_published_product(
            account_id=account_id,
            product_code=product_code,
            image_set=image_set,
        )
        if not row or str(row.status or "") != "on_sale":
            missing.append(selector)
            continue
        pdd_product_id = str(row.pdd_product_id or "").strip()
        mapping_id = str(row.mapping_id or "").strip()
        if not pdd_product_id or not mapping_id:
            missing.append(selector)
            continue
        pdd_ids.append(pdd_product_id)
        mapping_ids.append(mapping_id)
    return (
        list(dict.fromkeys(pdd_ids)),
        list(dict.fromkeys(mapping_ids)),
        missing,
    )


def _mark_listing_skipped_success(
    *,
    listing_run_id: str,
    account_id: str,
    selectors: list[str],
) -> dict[str, Any]:
    pdd_ids, mapping_ids, missing = resolve_published_products_for_pipeline(account_id, selectors)
    if missing:
        raise ValueError(f"无法跳过上架，未找到在售记录：{', '.join(missing)}")
    store = TaskRunStore()
    store.update_status(listing_run_id, RunStatus.RUNNING)
    results: list[dict[str, Any]] = []
    for selector in selectors:
        _family, image_set, product_code = _parse_pipeline_product_selector(selector)
        row = get_published_product(
            account_id=account_id,
            product_code=product_code,
            image_set=image_set,
        )
        if not row:
            continue
        results.append(
            {
                "status": "success",
                "pdd_product_id": str(row.pdd_product_id or "").strip(),
                "mapping_id": str(row.mapping_id or "").strip(),
                "listing_label": selector,
                "skipped_listing": True,
            }
        )
    message = f"跳过上架：复用 {len(pdd_ids)} 个已上架商品"
    payload = {"results": results, "listing_skipped": True}
    store.finish(listing_run_id, RunStatus.SUCCESS, message, result=payload)
    return payload


def _campaign_result_status_label(result: dict[str, Any]) -> str:
    if result.get("skipped"):
        return "已跳过"
    if result.get("success"):
        return "成功"
    return "失败"


def _build_multi_activity_detail(row, *, campaign_status: str) -> str:
    activity_ids = _pipeline_activity_ids(row)
    if len(activity_ids) <= 1:
        return ""
    results_by_id = {
        str(item.get("activity_id") or ""): item
        for item in _campaign_results(row)
        if str(item.get("activity_id") or "")
    }
    current_index = _campaign_activity_index(row)
    lines: list[str] = []
    for index, activity_id in enumerate(activity_ids):
        result = results_by_id.get(activity_id)
        if result:
            status_label = _campaign_result_status_label(result)
            summary = str(result.get("summary") or result.get("error") or "").strip()
            line = f"{index + 1}/{len(activity_ids)} {activity_id}：{status_label}"
            if summary:
                line += f"（{summary}）"
            lines.append(line)
            continue
        if index == current_index and row.campaign_run_id:
            if campaign_status == "scheduled" and row.scheduled_activity_at:
                lines.append(
                    f"{index + 1}/{len(activity_ids)} {activity_id}："
                    f"计划于 {row.scheduled_activity_at:%Y-%m-%d %H:%M} 报名"
                )
            else:
                lines.append(f"{index + 1}/{len(activity_ids)} {activity_id}：进行中")
        else:
            lines.append(f"{index + 1}/{len(activity_ids)} {activity_id}：待报名")
    return "；".join(lines)


def _derive_campaign_status(row, campaign_results: list[dict[str, Any]], activity_ids: list[str]) -> str:
    if row.current_step == "waiting_activity":
        return "scheduled"
    total = len(activity_ids)
    done = len(campaign_results)
    if total > 0 and done >= total:
        if all(item.get("skipped") for item in campaign_results):
            return "skipped"
        if all(item.get("success") for item in campaign_results):
            return "success"
        if any(item.get("skipped") for item in campaign_results):
            return "skipped"
        return "failed"
    if row.campaign_run_id:
        record = TaskRunStore().load(row.campaign_run_id)
        if record:
            return str(record.status.value if hasattr(record.status, "value") else record.status)
    return "pending"


def _step_infos(row) -> list[dict[str, Any]]:
    pipeline_canceled = row.status == "canceled"
    meta = dict(row.meta or {})
    campaign_outcome = str(meta.get("campaign_outcome") or "")
    campaign_skip_reason = str(meta.get("campaign_skip_reason") or "")
    listing_outcome = str(meta.get("listing_outcome") or "")
    listing_skip_reason = str(meta.get("listing_skip_reason") or "")
    listing_status = "pending"
    if listing_outcome == LISTING_SKIPPED_OUTCOME:
        listing_status = "skipped"
    elif row.listing_run_id:
        record = TaskRunStore().load(row.listing_run_id)
        if record:
            listing_status = str(record.status.value if hasattr(record.status, "value") else record.status)

    campaign_status = "pending"
    activity_ids = _pipeline_activity_ids(row)
    campaign_results = _campaign_results(row)
    if campaign_outcome in CAMPAIGN_SKIP_TRAFFIC_OUTCOMES and len(campaign_results) >= len(activity_ids):
        campaign_status = "skipped"
    else:
        campaign_status = _derive_campaign_status(row, campaign_results, activity_ids)

    traffic_status = "pending"
    if row.traffic_run_id:
        record = TaskRunStore().load(row.traffic_run_id)
        if record:
            traffic_status = str(record.status.value if hasattr(record.status, "value") else record.status)
    elif row.status == "completed" and row.auto_promotion:
        traffic_status = "skipped"
    elif row.status == "completed":
        traffic_status = "skipped"

    limited_time_status = "pending"
    limited_time_run_id = _pipeline_limited_time_run_id(row)
    if not _pipeline_auto_limited_time(row):
        limited_time_status = "skipped"
    elif limited_time_run_id:
        record = TaskRunStore().load(limited_time_run_id)
        if record:
            limited_time_status = str(record.status.value if hasattr(record.status, "value") else record.status)
    elif row.status == "completed":
        limited_time_status = "skipped"

    limited_time_outcome = str((row.meta or {}).get("limited_time_outcome") or "")
    limited_time_skip_reason = str((row.meta or {}).get("limited_time_skip_reason") or "")

    activity_detail = "等待限时限量购完成后预约"
    if row.scheduled_activity_at and campaign_status == "scheduled":
        activity_detail = f"计划于 {row.scheduled_activity_at:%Y-%m-%d %H:%M} 自动报名"
    elif _limited_time_completed(row) and campaign_status == "pending" and not row.scheduled_activity_at:
        activity_detail = "限时限量购已完成，等待预约活动报名"
    multi_detail = _build_multi_activity_detail(row, campaign_status=campaign_status)
    if multi_detail:
        activity_detail = multi_detail
    elif campaign_outcome in CAMPAIGN_SKIP_TRAFFIC_OUTCOMES:
        activity_detail = campaign_skip_reason or "商品暂不可报名活动，已跳过活动报名"
    elif limited_time_outcome == "failed" and _pipeline_continue_after_limited_time_failure(row):
        activity_detail = "限时限量购失败，仍按设置继续活动报名"
    elif _pipeline_continue_after_activity_failure(row) and any(
        isinstance(item, dict) and not item.get("success") and not item.get("skipped")
        for item in campaign_results
    ):
        activity_detail = "部分活动报名失败，已按设置继续后续活动/推广"

    traffic_detail = "全部活动处理完成后自动创建推广" if row.auto_promotion and len(activity_ids) > 1 else (
        "活动报名成功后自动创建推广" if row.auto_promotion else "未启用"
    )
    if campaign_outcome in CAMPAIGN_SKIP_TRAFFIC_OUTCOMES and row.auto_promotion:
        traffic_detail = "活动未报名，仍继续创建推广"
    elif limited_time_outcome == "failed" and _pipeline_continue_after_limited_time_failure(row) and row.auto_promotion:
        traffic_detail = "限时限量购失败，活动处理完成后仍继续推广"
    elif _pipeline_continue_after_activity_failure(row) and row.auto_promotion:
        traffic_detail = "活动有失败时仍按设置继续创建推广"

    limited_time_detail = (
        "上架完成后立即执行（先于活动报名，取消惊喜优惠）"
        if _pipeline_auto_limited_time(row)
        else "未启用"
    )
    if row.current_step == "waiting_limited_time":
        limited_time_detail = f"上架完成后约 {LIMITED_TIME_POST_LISTING_DELAY_SECONDS} 秒启动（等待浏览器释放）"
    elif listing_status in {"success", "completed"} and limited_time_status == "pending":
        limited_time_detail = "即将启动限时限量购（先于活动报名）"
    elif limited_time_outcome == "failed" and _pipeline_continue_after_limited_time_failure(row):
        limited_time_detail = limited_time_skip_reason or "限时限量购失败，仍将继续活动报名"

    listing_detail = "将素材上架到拼多多"
    if listing_outcome == LISTING_SKIPPED_OUTCOME:
        listing_detail = listing_skip_reason or "商品已上架，跳过上架步骤"

    steps = [
        {
            "key": "listing",
            "label": "上架",
            "status": listing_status,
            "run_id": row.listing_run_id or "",
            "detail": listing_detail,
        },
        {
            "key": "limited_time",
            "label": "限时限量购",
            "status": limited_time_status,
            "run_id": limited_time_run_id,
            "detail": limited_time_detail,
        },
        {
            "key": "activity",
            "label": "活动报名",
            "status": campaign_status,
            "run_id": row.campaign_run_id or "",
            "scheduled_at": row.scheduled_activity_at,
            "detail": activity_detail,
        },
        {
            "key": "traffic",
            "label": "推广",
            "status": traffic_status,
            "run_id": row.traffic_run_id or "",
            "detail": traffic_detail,
        },
    ]
    if pipeline_canceled:
        for step in steps:
            if step["status"] not in {"success", "completed", "skipped"}:
                step["status"] = "canceled"
                if step["key"] == "activity" and row.scheduled_activity_at:
                    step["detail"] = "已取消，不再自动报名"
                elif step["key"] == "limited_time":
                    step["detail"] = "已取消"
                elif step["key"] == "traffic":
                    step["detail"] = "已取消"
                elif step["key"] == "listing":
                    step["detail"] = "已取消"
    return steps


def pipeline_to_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "pipeline_id": row.pipeline_id,
        "account_id": row.account_id,
        "status": row.status,
        "current_step": row.current_step,
        "product_codes": list(row.product_codes or []),
        "activity_id": row.activity_id,
        "activity_ids": _pipeline_activity_ids(row),
        "auto_promotion": bool(row.auto_promotion),
        "auto_limited_time_setup": _pipeline_auto_limited_time(row),
        "continue_after_limited_time_failure": _pipeline_continue_after_limited_time_failure(row),
        "continue_after_activity_failure": _pipeline_continue_after_activity_failure(row),
        "limited_time_outcome": str((row.meta or {}).get("limited_time_outcome") or ""),
        "limited_time_skip_reason": str((row.meta or {}).get("limited_time_skip_reason") or ""),
        "activity_delay_hours": float(row.activity_delay_hours or 24.0),
        "demo_mode": bool(row.demo_mode),
        "slot_alignment_test": bool((row.meta or {}).get("slot_alignment_test")),
        "batch_id": str((row.meta or {}).get("batch_id") or ""),
        "activity_jitter_seconds": int((row.meta or {}).get("activity_jitter_seconds") or 0),
        "listing_run_id": row.listing_run_id or "",
        "campaign_run_id": row.campaign_run_id or "",
        "traffic_run_id": row.traffic_run_id or "",
        "pdd_product_ids": list(row.pdd_product_ids or []),
        "mapping_ids": list(row.mapping_ids or []),
        "scheduled_activity_at": row.scheduled_activity_at,
        "error": row.error or "",
        "campaign_outcome": str((row.meta or {}).get("campaign_outcome") or ""),
        "campaign_skip_reason": str((row.meta or {}).get("campaign_skip_reason") or ""),
        "listing_outcome": str((row.meta or {}).get("listing_outcome") or ""),
        "listing_skip_reason": str((row.meta or {}).get("listing_skip_reason") or ""),
        "listing_unit_statuses": build_listing_unit_statuses(row),
        "campaign_results": _campaign_results(row),
        "steps": _step_infos(row),
        "feishu_inspect_at": str((row.meta or {}).get("feishu_price_inspect_at") or ""),
        "has_feishu_inspect": bool((row.meta or {}).get("feishu_price_inspect")),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _merge_skipped_listing_products(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """将跳过上架的商品（已上架）的在售 ID 合并进链路。"""
    skip_selectors = [
        str(item).strip()
        for item in ((row.meta or {}).get("listing_skip_selectors") or [])
        if str(item).strip()
    ]
    if not skip_selectors:
        return pdd_ids, mapping_ids, []
    extra_pdd, extra_mapping, missing = resolve_published_products_for_pipeline(
        row.account_id,
        skip_selectors,
    )
    merged_pdd = list(dict.fromkeys([*pdd_ids, *extra_pdd]))
    merged_mapping = list(dict.fromkeys([*mapping_ids, *extra_mapping]))
    return merged_pdd, merged_mapping, missing


def start_integrated_pipeline(
    *,
    account_id: str,
    product_codes: list[str],
    activity_id: str = "",
    activity_ids: list[str] | None = None,
    category_keyword: str = "玩偶",
    auto_promotion: bool = True,
    auto_limited_time_setup: bool = True,
    continue_after_limited_time_failure: bool = False,
    continue_after_activity_failure: bool = False,
    activity_delay_hours: float = 24.0,
    demo_mode: bool = False,
    platform_listing_code: str = "",
    slot_alignment_test: bool = False,
    listing_scheduled_at: datetime | None = None,
    batch_id: str = "",
    skip_listing: bool = False,
    listing_skip_selectors: list[str] | None = None,
    material_source: str = "",
    listing_input_mode: ListingInputMode = "selector",
) -> dict[str, Any]:
    account_id = str(account_id or "").strip()
    normalized_activity_ids = _normalize_pipeline_activity_ids(activity_id, activity_ids)
    activity_id = normalized_activity_ids[0]
    if not account_id:
        raise ValueError("account_id is required")
    if not normalized_activity_ids:
        raise ValueError("activity_ids is required")

    codes, listing_input_meta = _resolve_pipeline_listing_codes(
        product_codes,
        listing_input_mode=listing_input_mode,
    )

    skip_selector_set = set(
        s for s in (listing_skip_selectors or []) if str(s).strip() in set(codes)
    )
    skip_selectors = [c for c in codes if c in skip_selector_set]
    list_codes = [c for c in codes if c not in skip_selector_set]

    pipeline_id = _pipeline_id()
    listing_run_id = create_listing_run(account_id)
    meta: dict[str, Any] = {
        "category_keyword": category_keyword,
        "platform_listing_code": platform_listing_code,
        "slot_alignment_test": bool(slot_alignment_test),
        "material_source": str(material_source or ""),
        "auto_limited_time_setup": bool(normalized_activity_ids),
        "continue_after_limited_time_failure": bool(continue_after_limited_time_failure),
        "continue_after_activity_failure": bool(continue_after_activity_failure),
        "activity_ids": normalized_activity_ids,
        "campaign_activity_index": 0,
        "campaign_results": [],
        **listing_input_meta,
    }
    if batch_id:
        meta["batch_id"] = batch_id
    if skip_selectors:
        meta["listing_skip_selectors"] = skip_selectors
    row = create_integrated_pipeline(
        pipeline_id=pipeline_id,
        account_id=account_id,
        product_codes=codes,
        activity_id=activity_id,
        auto_promotion=auto_promotion,
        activity_delay_hours=activity_delay_hours,
        demo_mode=demo_mode,
        listing_run_id=listing_run_id,
        meta=meta,
    )
    try:
        from pdd_agent.integrations.feishu.listing_feishu_inspect_store import (
            schedule_pipeline_feishu_inspect_capture,
        )

        schedule_pipeline_feishu_inspect_capture(pipeline_id, codes)
    except Exception:
        logger.exception("schedule pipeline feishu inspect failed pipeline_id=%s", pipeline_id)

    if skip_listing:
        skip_reason = f"商品已上架，跳过上架步骤（复用 {len(codes)} 个商品的在售记录）"
        listing_result = _mark_listing_skipped_success(
            listing_run_id=listing_run_id,
            account_id=account_id,
            selectors=codes,
        )
        update_integrated_pipeline(
            pipeline_id,
            meta_patch={
                "listing_outcome": LISTING_SKIPPED_OUTCOME,
                "listing_skip_reason": skip_reason,
            },
        )
        refreshed = get_integrated_pipeline(pipeline_id)
        _on_listing_finished(
            refreshed or row,
            run_id=listing_run_id,
            success=True,
            result=listing_result,
            error="",
        )
        logger.info(
            "integrated pipeline started with listing skipped pipeline_id=%s account=%s products=%s",
            pipeline_id,
            account_id,
            codes,
        )
        refreshed = get_integrated_pipeline(pipeline_id)
        return pipeline_to_dict(refreshed or row)

    if skip_selectors and not list_codes:
        skip_reason = f"商品已上架，跳过上架步骤（复用 {len(skip_selectors)} 个商品的在售记录）"
        listing_result = _mark_listing_skipped_success(
            listing_run_id=listing_run_id,
            account_id=account_id,
            selectors=skip_selectors,
        )
        update_integrated_pipeline(
            pipeline_id,
            meta_patch={
                "listing_outcome": LISTING_SKIPPED_OUTCOME,
                "listing_skip_reason": skip_reason,
            },
        )
        refreshed = get_integrated_pipeline(pipeline_id)
        _on_listing_finished(
            refreshed or row,
            run_id=listing_run_id,
            success=True,
            result=listing_result,
            error="",
        )
        refreshed = get_integrated_pipeline(pipeline_id)
        return pipeline_to_dict(refreshed or row)

    listing_codes = list_codes if skip_selectors else codes
    if skip_selectors:
        update_integrated_pipeline(
            pipeline_id,
            meta_patch={
                "listing_skip_reason": (
                    f"已上架 {len(skip_selectors)} 个商品跳过上架，"
                    f"待上架 {len(listing_codes)} 个商品执行上架"
                ),
            },
        )

    enqueue_task(
        agent=AgentKind.LISTING.value,
        run_id=listing_run_id,
        account_id=account_id,
        payload={
            "product_codes": listing_codes,
            "dry_run": False,
            "category_keyword": category_keyword,
            "platform_listing_code": platform_listing_code,
            "pipeline_id": pipeline_id,
            "slot_alignment_test": bool(slot_alignment_test),
            "material_source": str(material_source or ""),
        },
        scheduled_at=listing_scheduled_at or datetime.now(),
    )
    logger.info(
        "integrated pipeline started pipeline_id=%s account=%s activity=%s demo=%s",
        pipeline_id,
        account_id,
        activity_id,
        demo_mode,
    )
    refreshed = get_integrated_pipeline(pipeline_id)
    return pipeline_to_dict(refreshed or row)


def start_integrated_pipeline_batch(
    *,
    items: list[dict[str, Any]],
    activity_id: str = "",
    activity_ids: list[str] | None = None,
    category_keyword: str = "玩偶",
    auto_promotion: bool = True,
    auto_limited_time_setup: bool = True,
    continue_after_limited_time_failure: bool = False,
    continue_after_activity_failure: bool = False,
    activity_delay_hours: float = 24.0,
    demo_mode: bool = False,
    platform_listing_code: str = "",
    slot_alignment_test: bool = False,
    store_start_delay_min_seconds: int | None = None,
    store_start_delay_max_seconds: int | None = None,
    max_concurrent_stores: int | None = None,
    skip_listing: bool = False,
    listing_skip_selectors: list[str] | None = None,
    material_source: str = "",
) -> dict[str, Any]:
    """批量创建整合链路；各条链路上架任务按启动间隔错开入队。"""
    normalized_activity_ids = _normalize_pipeline_activity_ids(activity_id, activity_ids)
    activity_id = normalized_activity_ids[0] if normalized_activity_ids else ""
    if not normalized_activity_ids:
        raise ValueError("activity_ids is required")
    if not items:
        raise ValueError("items is required")

    batch_id = _batch_id()
    delay_range = resolve_batch_delay(store_start_delay_min_seconds, store_start_delay_max_seconds)
    max_concurrent = resolve_batch_concurrency(max_concurrent_stores)
    scheduled_at = datetime.now()
    pipelines: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        if index > 0 and delay_range[1] > 0:
            scheduled_at += timedelta(seconds=random.randint(delay_range[0], delay_range[1]))
        account_id = str(item.get("account_id") or "").strip()
        product_codes = list(item.get("product_codes") or [])
        data = start_integrated_pipeline(
            account_id=account_id,
            product_codes=product_codes,
            activity_id=activity_id,
            activity_ids=normalized_activity_ids,
            category_keyword=category_keyword,
            auto_promotion=auto_promotion,
            auto_limited_time_setup=auto_limited_time_setup,
            continue_after_limited_time_failure=continue_after_limited_time_failure,
            continue_after_activity_failure=continue_after_activity_failure,
            activity_delay_hours=activity_delay_hours,
            demo_mode=demo_mode,
            platform_listing_code=platform_listing_code,
            slot_alignment_test=slot_alignment_test,
            listing_scheduled_at=scheduled_at,
            batch_id=batch_id,
            skip_listing=skip_listing,
            listing_skip_selectors=listing_skip_selectors,
            material_source=material_source,
        )
        pipelines.append(
            {
                "account_id": data["account_id"],
                "pipeline_id": data["pipeline_id"],
                "listing_run_id": data["listing_run_id"],
                "listing_scheduled_at": scheduled_at,
            }
        )

    return {
        "batch_id": batch_id,
        "total": len(pipelines),
        "max_concurrent_stores": max_concurrent,
        "store_start_delay_min_seconds": delay_range[0],
        "store_start_delay_max_seconds": delay_range[1],
        "pipelines": pipelines,
        "message": (
            f"batch integrated pipeline queued: {len(pipelines)} pipelines, "
            f"concurrency {max_concurrent}, start delay {delay_range[0]}-{delay_range[1]}s"
        ),
    }


def on_queue_task_finished(
    *,
    agent: str,
    pipeline_id: str,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id:
        return
    row = get_integrated_pipeline(pipeline_id)
    if not row:
        return
    if row.status in TERMINAL_PIPELINE_STATUSES:
        return

    result = result if isinstance(result, dict) else {}
    if agent == AgentKind.LISTING.value:
        _on_listing_finished(row, run_id=run_id, success=success, result=result, error=error)
    elif agent == AgentKind.CAMPAIGN.value:
        if _pipeline_limited_time_run_id(row) == run_id:
            _on_limited_time_finished(row, run_id=run_id, success=success, result=result, error=error)
        else:
            _on_campaign_finished(row, run_id=run_id, success=success, result=result, error=error)
    elif agent == AgentKind.TRAFFIC.value:
        _on_traffic_finished(row, run_id=run_id, success=success, error=error)

    try:
        from pdd_agent.api.services.pipeline_issue_report_service import ingest_queue_task_outcome

        ingest_queue_task_outcome(
            pipeline_row=row,
            pipeline_id=pipeline_id,
            agent=agent,
            run_id=run_id,
            success=success,
            result=result,
            error=error,
        )
    except Exception:
        logger.warning("pipeline issue ingest failed pipeline_id=%s", pipeline_id, exc_info=True)

    _ensure_pipeline_failed_after_task(
        pipeline_id=pipeline_id,
        agent=agent,
        run_id=run_id,
        success=success,
        error=error,
        result=result,
    )


def _listing_failure_meta(result: dict[str, Any]) -> dict[str, Any]:
    """统计 preflight/上架失败套图，成功商品仍继续整合链路。"""
    failed_labels: list[str] = []

    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        product_id = str(item.get("pdd_product_id") or "").strip()
        if status in {"success", "listed"} and bool(product_id or status == "listed"):
            continue
        if status in {"failed", "retryable"} or item.get("error") or item.get("reason"):
            label = str(item.get("listing_label") or "").strip()
            if label:
                failed_labels.append(label)

    preflight = result.get("preflight")
    issues: list[Any] = []
    if isinstance(preflight, dict):
        issues = list(preflight.get("issues") or [])
    elif preflight is not None:
        issues = list(getattr(preflight, "issues", None) or [])
    for issue in issues:
        level = str(
            getattr(issue, "level", None) or (issue.get("level") if isinstance(issue, dict) else "") or ""
        )
        if level != "error":
            continue
        label = str(
            getattr(issue, "listing_label", None)
            or (issue.get("listing_label") if isinstance(issue, dict) else "")
            or ""
        ).strip()
        if label:
            failed_labels.append(label)

    unique = list(dict.fromkeys(failed_labels))
    if not unique:
        return {}
    return {
        "listing_outcome": LISTING_PARTIAL_OUTCOME,
        "listing_failed_labels": unique,
        "listing_failed_count": len(unique),
    }


def _on_listing_finished(row, *, run_id: str, success: bool, result: dict[str, Any], error: str) -> None:
    if not success:
        err = error or "上架失败"
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="listing_failed",
            error=err,
        )
        _try_wecom_pipeline_failed(row, error=err, current_step="listing_failed")
        return

    pdd_ids, mapping_ids = _extract_listing_products(result)
    pdd_ids, mapping_ids, missing = _merge_skipped_listing_products(row, pdd_ids=pdd_ids, mapping_ids=mapping_ids)
    if missing:
        err = f"跳过上架的商品未找到在售记录：{', '.join(missing)}"
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="listing_failed",
            error=err,
        )
        _try_wecom_pipeline_failed(row, error=err, current_step="listing_failed")
        try:
            from pdd_agent.api.services.pipeline_issue_report_service import ingest_orchestration_issue

            ingest_orchestration_issue(
                pipeline_row=row,
                pipeline_id=row.pipeline_id,
                chain_step="listing_skip_lookup_failed",
                reason_code="skip_listing_lookup_failed",
                message=f"跳过上架的商品未找到在售记录：{', '.join(missing)}",
                run_id=run_id,
                source_location="pipeline_service._on_listing_finished",
            )
        except Exception:
            logger.warning("pipeline issue ingest failed pipeline_id=%s", row.pipeline_id, exc_info=True)
        return
    if not pdd_ids:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="listing_failed",
            error="上架完成但未获取到拼多多商品 ID",
        )
        try:
            from pdd_agent.api.services.pipeline_issue_report_service import ingest_orchestration_issue

            ingest_orchestration_issue(
                pipeline_row=row,
                pipeline_id=row.pipeline_id,
                chain_step="listing_no_pdd_ids",
                reason_code="listing_no_pdd_ids",
                message="上架步骤显示成功，但未获取到拼多多商品 ID，链路无法继续",
                run_id=run_id,
                context={"result_summary": _summarize_run_message(run_id)},
                source_location="pipeline_service._on_listing_finished",
            )
        except Exception:
            logger.warning("pipeline issue ingest failed pipeline_id=%s", row.pipeline_id, exc_info=True)
        return

    listing_meta = {
        "listing_summary": _summarize_run_message(run_id),
    }
    listing_meta.update(_listing_failure_meta(result))
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    if _pipeline_auto_limited_time(refreshed):
        limited_time_at = datetime.now() + timedelta(seconds=LIMITED_TIME_POST_LISTING_DELAY_SECONDS)
        _enqueue_pipeline_limited_time(
            refreshed,
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
            meta_patch=listing_meta,
            scheduled_at=limited_time_at,
        )
        logger.info(
            "pipeline %s listing done, limited time scheduled at %s pdd_ids=%s activities=%s",
            row.pipeline_id,
            limited_time_at,
            pdd_ids,
            _pipeline_activity_ids(row),
        )
        return

    scheduled_at = resolve_activity_scheduled_at(
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )
    base_at = datetime.now() + _resolve_activity_delay(
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )
    activity_jitter_seconds = max(0, int((scheduled_at - base_at).total_seconds()))
    listing_meta["activity_jitter_seconds"] = activity_jitter_seconds
    _schedule_pipeline_campaign(
        row,
        activity_index=0,
        scheduled_at=scheduled_at,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        meta_patch=listing_meta,
    )
    logger.info(
        "pipeline %s listing done, activity scheduled at %s pdd_ids=%s activities=%s",
        row.pipeline_id,
        scheduled_at,
        pdd_ids,
        _pipeline_activity_ids(row),
    )


def _format_multi_campaign_skip_reason(
    row,
    meta_patch: dict[str, Any],
    latest_reason: str,
) -> str:
    results = meta_patch.get("campaign_results")
    if not isinstance(results, list):
        results = _campaign_results(row)
    skipped_parts = [
        f"活动 {item.get('activity_id')}: {item.get('summary') or item.get('error')}"
        for item in results
        if isinstance(item, dict) and item.get("skipped")
    ]
    if skipped_parts:
        return "；".join(str(part) for part in skipped_parts if part)
    return latest_reason


def _on_campaign_finished(row, *, run_id: str, success: bool, result: dict[str, Any], error: str) -> None:
    if _campaign_run_already_handled(row, run_id):
        logger.debug(
            "skip duplicate campaign finished pipeline=%s run_id=%s",
            row.pipeline_id,
            run_id,
        )
        return
    activity_ids = _pipeline_activity_ids(row)
    current_index = _campaign_activity_index(row)
    current_activity_id = (
        activity_ids[current_index] if current_index < len(activity_ids) else str(row.activity_id or "")
    )
    activity_skipped = (not success) and _should_skip_campaign_for_traffic(result, error)
    activity_continue = (
        (not success)
        and not activity_skipped
        and _pipeline_continue_after_activity_failure(row)
    )
    campaign_summary = _summarize_run_message(run_id)
    meta_patch: dict[str, Any] = {"campaign_summary": campaign_summary}
    _mark_campaign_run_handled(meta_patch, run_id)

    if not success and not activity_skipped and not activity_continue:
        _append_campaign_result(
            meta_patch,
            row,
            activity_id=current_activity_id,
            run_id=run_id,
            success=False,
            skipped=False,
            error=error or "活动报名失败",
            summary=campaign_summary,
        )
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="activity_failed",
            error=error or "活动报名失败",
            meta_patch=meta_patch,
        )
        return

    _append_campaign_result(
        meta_patch,
        row,
        activity_id=current_activity_id,
        run_id=run_id,
        success=bool(success),
        skipped=activity_skipped,
        error=error if (activity_skipped or activity_continue) else "",
        summary=campaign_summary,
    )

    if activity_skipped:
        skip_reason = _campaign_skip_message(result, error)
        meta_patch["campaign_outcome"] = _campaign_skip_outcome(result)
        meta_patch["campaign_skip_reason"] = _format_multi_campaign_skip_reason(row, meta_patch, skip_reason)
        logger.info(
            "pipeline %s activity %s skipped (%s)",
            row.pipeline_id,
            current_activity_id,
            meta_patch["campaign_outcome"],
        )
    elif activity_continue:
        meta_patch["campaign_outcome"] = "activity_failed_continue"
        meta_patch["campaign_skip_reason"] = _format_multi_campaign_skip_reason(
            row,
            meta_patch,
            error or "活动报名失败",
        )
        update_integrated_pipeline(
            row.pipeline_id,
            status="running",
            current_step="activity_failed_continue",
            error="",
            meta_patch=meta_patch,
        )
        logger.info(
            "pipeline %s activity %s failed, continuing per setting: %s",
            row.pipeline_id,
            current_activity_id,
            error or "活动报名失败",
        )

    next_index = current_index + 1
    if next_index < len(activity_ids):
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        _schedule_pipeline_campaign(
            refreshed,
            activity_index=next_index,
            scheduled_at=datetime.now(),
            meta_patch=meta_patch,
        )
        logger.info(
            "pipeline %s scheduled next activity %s (%s/%s)",
            row.pipeline_id,
            activity_ids[next_index],
            next_index + 1,
            len(activity_ids),
        )
        return

    meta_patch["campaign_activity_index"] = len(activity_ids)
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    if not refreshed.auto_promotion:
        final_status = "completed"
        final_step = "completed"
        final_error = ""
        if activity_continue or any(
            isinstance(item, dict) and not item.get("success") and not item.get("skipped")
            for item in _campaign_results(refreshed)
        ):
            final_status = "completed"
            meta_patch.setdefault("campaign_outcome", "partial_activity_failure")
        update_integrated_pipeline(
            row.pipeline_id,
            status=final_status,
            current_step=final_step,
            error=final_error,
            meta_patch=meta_patch,
        )
        return

    _enqueue_pipeline_traffic(refreshed, meta_patch=meta_patch)


def _on_limited_time_finished(row, *, run_id: str, success: bool, result: dict[str, Any], error: str) -> None:
    meta = dict(row.meta or {})
    if meta.get("limited_time_finish_handled"):
        return
    meta_patch: dict[str, Any] = {
        "limited_time_finish_handled": True,
        "limited_time_summary": _summarize_run_message(run_id),
    }
    if not success:
        meta_patch["limited_time_outcome"] = "failed"
        failure_message = error or "限时限量购设置失败"
        if _pipeline_continue_after_limited_time_failure(row):
            meta_patch["limited_time_skip_reason"] = failure_message
            update_integrated_pipeline(
                row.pipeline_id,
                status="running",
                current_step="limited_time_failed_continue",
                error="",
                meta_patch=meta_patch,
            )
            refreshed = get_integrated_pipeline(row.pipeline_id) or row
            _schedule_pipeline_activity_after_limited_time(refreshed, meta_patch=meta_patch)
            logger.info(
                "pipeline %s limited time failed, continuing to activity: %s",
                row.pipeline_id,
                failure_message,
            )
            return
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="limited_time_failed",
            error=failure_message,
            meta_patch=meta_patch,
        )
        return

    meta_patch["limited_time_outcome"] = "success"

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    _schedule_pipeline_activity_after_limited_time(refreshed, meta_patch=meta_patch)


def _on_traffic_finished(row, *, run_id: str, success: bool, error: str) -> None:
    meta = dict(row.meta or {})
    if meta.get("traffic_finish_handled"):
        logger.debug(
            "skip duplicate traffic finished pipeline=%s run_id=%s",
            row.pipeline_id,
            run_id,
        )
        return
    if not success:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="traffic_failed",
            error=error or "推广创建失败",
            meta_patch={"traffic_finish_handled": True},
        )
        return
    update_integrated_pipeline(
        row.pipeline_id,
        status="completed",
        current_step="completed",
        error="",
        meta_patch={
            "traffic_summary": _summarize_run_message(run_id),
            "traffic_finish_handled": True,
        },
    )


def _run_status_value(status) -> str:
    if status is None:
        return ""
    return str(status.value if hasattr(status, "value") else status)


def _reconcile_stuck_pipeline_row(row) -> Any:
    """子任务已失败/取消但链路仍 running 时自动对齐（例如浏览器被关后回调未触发）。"""
    if not row or row.status in TERMINAL_PIPELINE_STATUSES:
        return row
    store = TaskRunStore()
    checks = [
        (row.listing_run_id, "listing_failed", "上架失败"),
        (row.campaign_run_id, "activity_failed", "活动报名失败"),
        (_pipeline_limited_time_run_id(row), "limited_time_failed", "限时限量购设置失败"),
        (row.traffic_run_id, "traffic_failed", "推广创建失败"),
    ]
    for run_id, failed_step, default_error in checks:
        if not run_id:
            continue
        record = store.load(run_id)
        if not record:
            continue
        run_status = _run_status_value(record.status)
        if run_status not in {RunStatus.FAILED, RunStatus.CANCELED}:
            continue
        error = str(record.message or "").strip() or default_error
        if run_status == RunStatus.CANCELED:
            error = error or "子任务已取消"
        if (
            run_id == _pipeline_limited_time_run_id(row)
            and run_status == RunStatus.FAILED
            and _pipeline_continue_after_limited_time_failure(row)
        ):
            refreshed = get_integrated_pipeline(row.pipeline_id) or row
            refreshed_meta = refreshed.meta if isinstance(refreshed.meta, dict) else {}
            if (
                not refreshed.campaign_run_id
                and not refreshed.scheduled_activity_at
                and not refreshed_meta.get("limited_time_finish_handled")
            ):
                _on_limited_time_finished(
                    refreshed,
                    run_id=run_id,
                    success=False,
                    result=record.result if isinstance(record.result, dict) else {},
                    error=str(record.message or "").strip() or "限时限量购设置失败",
                )
            continue
        if (
            run_id == row.campaign_run_id
            and run_status == RunStatus.FAILED
            and _pipeline_continue_after_activity_failure(row)
        ):
            refreshed = get_integrated_pipeline(row.pipeline_id) or row
            _on_campaign_finished(
                refreshed,
                run_id=run_id,
                success=False,
                result=record.result if isinstance(record.result, dict) else {},
                error=str(record.message or "").strip() or "活动报名失败",
            )
            continue
        error = str(record.message or "").strip() or default_error
        if run_status == RunStatus.CANCELED:
            error = error or "子任务已取消"
        updated = update_integrated_pipeline(
            row.pipeline_id,
            status="failed" if run_status == RunStatus.FAILED else "canceled",
            current_step=failed_step if run_status == RunStatus.FAILED else "canceled",
            error=error,
        )
        if updated:
            logger.warning(
                "reconciled stuck pipeline %s from run %s status=%s",
                row.pipeline_id,
                run_id,
                run_status,
            )
            return get_integrated_pipeline(row.pipeline_id) or updated
    return row


def _ensure_pipeline_failed_after_task(
    *,
    pipeline_id: str,
    agent: str,
    run_id: str = "",
    success: bool,
    error: str,
    result: dict[str, Any] | None = None,
) -> None:
    if success:
        return
    row = get_integrated_pipeline(pipeline_id)
    if not row or row.status in TERMINAL_PIPELINE_STATUSES:
        return
    if (
        agent == AgentKind.CAMPAIGN.value
        and _pipeline_limited_time_run_id(row) != run_id
        and _should_skip_campaign_for_traffic(result if isinstance(result, dict) else None, error)
    ):
        return
    if (
        agent == AgentKind.CAMPAIGN.value
        and _pipeline_limited_time_run_id(row) == run_id
        and _pipeline_continue_after_limited_time_failure(row)
    ):
        return
    if (
        agent == AgentKind.CAMPAIGN.value
        and _pipeline_limited_time_run_id(row) != run_id
        and _pipeline_continue_after_activity_failure(row)
    ):
        return
    step_map = {
        AgentKind.LISTING.value: ("listing_failed", "上架失败"),
        AgentKind.CAMPAIGN.value: ("activity_failed", "活动报名失败"),
        AgentKind.TRAFFIC.value: ("traffic_failed", "推广创建失败"),
    }
    failed_step, default_error = step_map.get(agent, ("failed", "链路失败"))
    err = str(error or "").strip() or default_error
    update_integrated_pipeline(
        pipeline_id,
        status="failed",
        current_step=failed_step,
        error=err,
    )
    _try_wecom_pipeline_failed(row, error=err, current_step=failed_step)


def _summarize_run_message(run_id: str) -> str:
    record = TaskRunStore().load(run_id)
    return str(record.message or "") if record else ""


def get_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    row = get_integrated_pipeline(pipeline_id)
    if row:
        row = _reconcile_stuck_pipeline_row(row)
    return pipeline_to_dict(row) if row else None


def list_pipelines(
    *,
    page: int = 1,
    page_size: int = 10,
    batch_id: str = "",
) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 50))
    offset = (page - 1) * page_size
    total = count_integrated_pipelines(batch_id=batch_id)
    rows = list_integrated_pipelines(limit=page_size, offset=offset, batch_id=batch_id)
    reconciled = [
        _reconcile_stuck_pipeline_row(row) if row.status == "running" else row
        for row in rows
    ]
    items = [pipeline_to_dict(row) for row in reconciled]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def cancel_integrated_pipeline(pipeline_id: str) -> dict[str, Any]:
    """取消整合链路：停止排队/运行中的子任务，后续步骤不再执行。"""
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id:
        raise ValueError("pipeline_id is required")

    row = get_integrated_pipeline(pipeline_id)
    if not row:
        raise ValueError("pipeline not found")
    if row.status in TERMINAL_PIPELINE_STATUSES:
        raise ValueError(f"pipeline already {row.status}")

    run_ids = [rid for rid in (row.listing_run_id, row.campaign_run_id, row.traffic_run_id) if rid]
    pending_run_ids: list[str] = []
    store = TaskRunStore()
    for run_id in run_ids:
        record = store.load(run_id)
        if record and record.status in {RunStatus.PENDING, RunStatus.RUNNING}:
            pending_run_ids.append(run_id)

    from pdd_agent.api.app import worker

    worker.cancel_run_ids(run_ids)

    update_integrated_pipeline(
        pipeline_id,
        status="canceled",
        current_step="canceled",
        error="用户取消",
    )
    try:
        from pdd_agent.api.services.pipeline_issue_report_service import ingest_pipeline_canceled

        ingest_pipeline_canceled(
            pipeline_row=row,
            pipeline_id=pipeline_id,
            pending_run_ids=pending_run_ids,
        )
    except Exception:
        logger.warning("pipeline issue ingest failed pipeline_id=%s", pipeline_id, exc_info=True)
    logger.info("integrated pipeline canceled pipeline_id=%s canceled_runs=%s", pipeline_id, pending_run_ids)
    refreshed = get_integrated_pipeline(pipeline_id)
    return pipeline_to_dict(refreshed or row)

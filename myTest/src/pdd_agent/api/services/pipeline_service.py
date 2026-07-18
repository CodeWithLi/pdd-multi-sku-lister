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


def _pipeline_has_revived_scheduled_activity(row) -> bool:
    """分批限时重跑改期后：failed 链路仍应继续执行活动/推广队列任务。"""
    if not row:
        return False
    meta = dict(row.meta or {}) if isinstance(getattr(row, "meta", None), dict) else {}
    defer = dict(meta.get("pipeline_batch_lt_retry_activity_defer") or {})
    return bool(
        meta.get("batch_lt_retry_revived_activity")
        or defer.get("rescheduled")
        or defer.get("awaiting_reschedule")
        or getattr(row, "scheduled_activity_at", None)
    )


def _should_process_queue_task_on_terminal_pipeline(row, *, agent: str, run_id: str) -> bool:
    """终态链路中，仅允许「已改期活动/推广」的队列任务继续驱动编排。"""
    if str(getattr(row, "status", "") or "") != "failed":
        return False
    if not _pipeline_has_revived_scheduled_activity(row):
        return False
    rid = str(run_id or "").strip()
    if not rid:
        return False
    if str(agent or "") == AgentKind.CAMPAIGN.value:
        return rid == str(row.campaign_run_id or "").strip()
    if str(agent or "") == AgentKind.TRAFFIC.value:
        return rid == str(row.traffic_run_id or "").strip()
    return False


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
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        is_activity_limited_time_success_only_row,
    )

    if is_activity_limited_time_success_only_row(row):
        return False
    return bool((row.meta or {}).get("continue_after_limited_time_failure"))


def _pipeline_activity_limited_time_success_only(row) -> bool:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        is_activity_limited_time_success_only_row,
    )

    return is_activity_limited_time_success_only_row(row)


def _pipeline_continue_after_activity_failure(row) -> bool:
    """活动报名失败后仍继续下一个活动，并在全部处理完后继续推广。"""
    return bool((row.meta or {}).get("continue_after_activity_failure"))


def _pipeline_promote_after_limited_time_failure(row) -> bool:
    """限时限量购失败导致活动不跑时，仍跳过活动并创建推广。"""
    return bool((row.meta or {}).get("promote_after_limited_time_failure"))


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


def _try_advance_store_sequential_after_listing_limited_time(row) -> None:
    """上架+限时限量购阶段完成后尝试启动串行队列中的下一家店铺。"""
    if not row:
        return
    try:
        from pdd_agent.api.services.pipeline_store_sequential import (
            maybe_advance_sequential_store_after_listing_limited_time,
        )

        maybe_advance_sequential_store_after_listing_limited_time(row)
    except Exception:
        logger.exception(
            "advance sequential store after listing+limited-time failed pipeline_id=%s",
            row.pipeline_id,
        )


def _schedule_pipeline_activity_after_limited_time(
    row,
    *,
    meta_patch: dict[str, Any] | None = None,
    pdd_ids: list[str] | None = None,
    mapping_ids: list[str] | None = None,
) -> None:
    from pdd_agent.api.services.pipeline_activity_traffic_batch.bridge import (
        maybe_start_after_limited_time as maybe_start_activity_traffic_batch,
    )

    if maybe_start_activity_traffic_batch(
        row,
        meta_patch=meta_patch,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    ):
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        _try_advance_store_sequential_after_listing_limited_time(refreshed)
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
    patch = dict(meta_patch or {})
    patch["activity_jitter_seconds"] = activity_jitter_seconds
    _schedule_pipeline_campaign(
        row,
        activity_index=0,
        scheduled_at=scheduled_at,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        meta_patch=patch,
    )
    logger.info(
        "pipeline %s limited time done, activity scheduled at %s activities=%s",
        row.pipeline_id,
        scheduled_at,
        _pipeline_activity_ids(row),
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    _try_advance_store_sequential_after_listing_limited_time(refreshed)


def _enqueue_pipeline_traffic(row, *, meta_patch: dict[str, Any] | None = None) -> None:
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    if _pipeline_traffic_already_enqueued(refreshed):
        logger.info(
            "skip duplicate traffic enqueue pipeline=%s traffic_run_id=%s",
            refreshed.pipeline_id,
            refreshed.traffic_run_id,
        )
        return
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        resolve_activity_product_ids_for_row,
    )

    pdd_ids, mapping_ids = resolve_activity_product_ids_for_row(refreshed)
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
    "platform_skip_dedupe": "平台不适用已跳过",
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

    from pdd_agent.api.services.pipeline_listing_unit_results import (
        classify_listing_unit_pipeline_status,
        index_listing_result_items,
        load_pipeline_listing_skip_result_index,
        merge_listing_result_indexes,
        resolve_listing_result_item,
    )

    preflight_errors: dict[str, str] = {}
    valid_labels: set[str] = set()
    current_run_index: dict[str, dict[str, Any]] = {}
    run_status = ""
    run_phase = ""

    throttle = dict(meta.get("listing_throttle") or {})
    unit_results_raw = throttle.get("unit_results_by_label")
    accumulated_index = index_listing_result_items(
        [
            item
            for item in (unit_results_raw or {}).values()
            if isinstance(unit_results_raw, dict) and isinstance(item, dict)
        ]
    )

    if row.listing_run_id:
        record = TaskRunStore().load(row.listing_run_id)
        if record:
            run_status = str(
                record.status.value if hasattr(record.status, "value") else record.status
            )
            run_phase = str(record.phase.value if hasattr(record.phase, "value") else record.phase)
            result = dict(record.result or {})
            preflight_errors, valid_labels = _parse_preflight_snapshot(result)
            current_run_index = index_listing_result_items(result.get("results") or [])

    result_by_label = merge_listing_result_indexes(accumulated_index, current_run_index)

    if throttle.get("enabled"):
        store = TaskRunStore()
        seen_run_ids: set[str] = set()
        if row.listing_run_id:
            seen_run_ids.add(str(row.listing_run_id))
        run_ids_to_scan = [
            str(item).strip() for item in (throttle.get("batch_run_ids") or []) if str(item).strip()
        ]
        pipeline_id = str(getattr(row, "pipeline_id", "") or "").strip()
        if pipeline_id:
            try:
                from pdd_agent.db.repositories import list_listing_run_ids_for_pipeline

                for rid in list_listing_run_ids_for_pipeline(pipeline_id):
                    if rid not in run_ids_to_scan:
                        run_ids_to_scan.append(rid)
            except Exception:
                pass
        batch_indexes: list[dict[str, dict[str, Any]]] = []
        for run_id in run_ids_to_scan:
            rid = str(run_id or "").strip()
            if not rid or rid in seen_run_ids:
                continue
            seen_run_ids.add(rid)
            prior = store.load(rid)
            if not prior:
                continue
            prior_result = dict(prior.result or {})
            batch_indexes.append(index_listing_result_items(prior_result.get("results") or []))
        result_by_label = merge_listing_result_indexes(result_by_label, *batch_indexes)

    pipeline_id = str(getattr(row, "pipeline_id", "") or "").strip()
    if pipeline_id:
        skip_index = load_pipeline_listing_skip_result_index(pipeline_id)
        result_by_label = merge_listing_result_indexes(skip_index, result_by_label)

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
        elif resolve_listing_result_item(result_by_label, selector):
            item = resolve_listing_result_item(result_by_label, selector) or {}
            status, reason_code = classify_listing_unit_pipeline_status(item)
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


def _selector_parts(selector: str) -> list[str]:
    return [part.strip() for part in str(selector or "").split("/") if part.strip()]


def _looks_like_image_set_segment(text: str) -> bool:
    segment = str(text or "").strip()
    return bool(segment) and segment.endswith("套图")


def _lookup_published_row_for_pipeline_selector(account_id: str, selector: str):
    """按 selector 查在售 published_products；兼容 listing_label 的 product_code/套图 两段式。"""
    parts = _selector_parts(selector)
    if not parts:
        return None

    _family, image_set, product_code = _parse_pipeline_product_selector(selector)
    if product_code:
        row = get_published_product(
            account_id=account_id,
            product_code=product_code,
            image_set=image_set,
        )
        if row and str(row.status or "") == "on_sale":
            return row

    if len(parts) == 2 and _looks_like_image_set_segment(parts[1]):
        row = get_published_product(
            account_id=account_id,
            product_code=parts[0],
            image_set=parts[1],
        )
        if row and str(row.status or "") == "on_sale":
            return row

    return None


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
        row = _lookup_published_row_for_pipeline_selector(account_id, selector)
        if not row:
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
    listing_lt_phase_done = bool(meta.get("listing_limited_time_phase_completed"))
    campaign_outcome = str(meta.get("campaign_outcome") or "")
    campaign_skip_reason = str(meta.get("campaign_skip_reason") or "")
    listing_outcome = str(meta.get("listing_outcome") or "")
    listing_skip_reason = str(meta.get("listing_skip_reason") or "")
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
        build_batch_lt_retry_activity_defer_public_state,
    )

    batch_lt_activity_defer = build_batch_lt_retry_activity_defer_public_state(row)
    revived_activity = bool(
        meta.get("batch_lt_retry_revived_activity")
        or batch_lt_activity_defer.get("awaiting_reschedule")
        or batch_lt_activity_defer.get("rescheduled")
    )
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
    if revived_activity and str(row.current_step or "") == "waiting_activity":
        campaign_status = "scheduled" if row.scheduled_activity_at else "pending"
    elif campaign_outcome in CAMPAIGN_SKIP_TRAFFIC_OUTCOMES and len(campaign_results) >= len(activity_ids):
        campaign_status = "skipped"
    else:
        campaign_status = _derive_campaign_status(row, campaign_results, activity_ids)

    traffic_status = "pending"
    if revived_activity and str(row.current_step or "") == "waiting_activity":
        traffic_status = "pending"
    elif row.traffic_run_id:
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

    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        resolve_limited_time_step_display,
    )

    agg_lt_display = resolve_limited_time_step_display(row)
    if agg_lt_display:
        limited_time_status = str(agg_lt_display.get("status") or limited_time_status)
        if agg_lt_display.get("outcome"):
            limited_time_outcome = str(agg_lt_display.get("outcome") or limited_time_outcome)

    activity_detail = "等待限时限量购完成后预约"
    if batch_lt_activity_defer.get("rescheduled") and row.scheduled_activity_at:
        activity_detail = (
            f"计划于 {row.scheduled_activity_at:%Y-%m-%d %H:%M} 自动报名"
            f"（{batch_lt_activity_defer.get('reschedule_reason') or '分批限时重跑后改期'}）"
        )
    elif batch_lt_activity_defer.get("awaiting_reschedule"):
        anchor_raw = str(batch_lt_activity_defer.get("limited_time_finished_at") or "").strip()
        delay_h = float(row.activity_delay_hours or 24.0)
        if anchor_raw:
            try:
                anchor = datetime.fromisoformat(anchor_raw)
                from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
                    resolve_activity_scheduled_at_from_anchor,
                )

                planned_at = resolve_activity_scheduled_at_from_anchor(
                    anchor=anchor,
                    demo_mode=bool(row.demo_mode),
                    activity_delay_hours=delay_h,
                )
                activity_detail = (
                    f"分批限时重跑已成功，计划于 {planned_at:%Y-%m-%d %H:%M} 自动报名"
                    f"（最后成功批次完成时刻 + {delay_h:g}h）"
                )
            except ValueError:
                activity_detail = (
                    f"分批限时重跑已成功，活动将按最后成功批次完成时刻 + {delay_h:g}h 预约"
                )
        else:
            activity_detail = "分批限时重跑已成功，等待活动改期预约"
    if str(row.current_step or "") == "waiting_mq_phase2":
        from pdd_agent.api.services.pipeline_mq_auto_commerce import format_mq_phase2_wait_detail

        wait_detail = format_mq_phase2_wait_detail(meta)
        if meta.get("mq_phase2_wait_reason"):
            activity_detail = wait_detail
        elif row.scheduled_activity_at and row.scheduled_activity_at > datetime.now():
            activity_detail = (
                f"上架与限时限量购已完成，店铺已释放；"
                f"计划于 {row.scheduled_activity_at:%Y-%m-%d %H:%M} 后启动活动/推广"
            )
        else:
            activity_detail = "上架与限时限量购已完成，店铺已释放；活动/推广到期后等待店铺空闲再执行"
    if listing_lt_phase_done and row.current_step in {"waiting_activity", "campaign_queued"}:
        activity_detail = "上架与限时限量购已完成，活动按预约时间执行"
    if row.scheduled_activity_at and campaign_status == "scheduled":
        activity_detail = f"计划于 {row.scheduled_activity_at:%Y-%m-%d %H:%M} 自动报名"
    elif _limited_time_completed(row) and campaign_status == "pending" and not row.scheduled_activity_at:
        activity_detail = "限时限量购已完成，等待预约活动报名"
    multi_detail = _build_multi_activity_detail(row, campaign_status=campaign_status)
    if multi_detail:
        activity_detail = multi_detail
    elif campaign_outcome in CAMPAIGN_SKIP_TRAFFIC_OUTCOMES and not revived_activity:
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

    from pdd_agent.api.services.pipeline_activity_traffic_batch.bridge import (
        resolve_activity_traffic_batch_step_hint,
    )

    at_batch_hint = resolve_activity_traffic_batch_step_hint(row)
    if at_batch_hint:
        activity_detail = at_batch_hint
        if row.auto_promotion:
            traffic_detail = f"{at_batch_hint}；本批活动完成后创建推广"

    from pdd_agent.api.services.pipeline_per_batch_lt_chunks.bridge import (
        resolve_limited_time_step_chunk_hint,
    )

    chunk_lt_hint = resolve_limited_time_step_chunk_hint(row)

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
    elif agg_lt_display and agg_lt_display.get("detail"):
        limited_time_detail = str(agg_lt_display.get("detail") or limited_time_detail)
    elif chunk_lt_hint:
        limited_time_detail = chunk_lt_hint
    elif listing_lt_phase_done:
        limited_time_detail = "已完成（活动已预约，不阻塞下一家店铺）"

    listing_detail = "将素材上架到拼多多"
    if listing_outcome == LISTING_SKIPPED_OUTCOME:
        listing_detail = listing_skip_reason or "商品已上架，跳过上架步骤"
    else:
        from pdd_agent.api.services.pipeline_listing_throttle import throttle_listing_detail

        throttle_hint = throttle_listing_detail(dict(meta.get("listing_throttle") or {}))
        if throttle_hint:
            listing_detail = throttle_hint
        if str(row.current_step or "").startswith("waiting_listing_batch_"):
            throttle = dict(meta.get("listing_throttle") or {})
            next_at = str(throttle.get("next_batch_scheduled_at") or "")
            if next_at:
                listing_detail = f"{listing_detail}；下一批约 {next_at}"

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
    from pdd_agent.api.services.pipeline_lt_failure_promotion_policy import (
        enrich_pipeline_step_infos,
    )

    enrich_pipeline_step_infos(
        steps,
        row,
        meta=meta,
        limited_time_outcome=limited_time_outcome,
        campaign_outcome=campaign_outcome,
        campaign_skip_reason=campaign_skip_reason,
        auto_promotion=bool(row.auto_promotion),
    )
    return steps


def _per_batch_lt_aggregate_public_state(row) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        is_standard_per_batch_lt_pipeline,
    )
    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.constants import (
        AGG_BATCH_LOG_KEY,
        AGG_FINALIZED_KEY,
        AGG_IN_PROGRESS_KEY,
        AGG_OUTCOME_KEY,
        AGG_PDD_IDS_KEY,
    )

    if not is_standard_per_batch_lt_pipeline(row):
        return {}
    meta = dict(row.meta or {})
    pdd_ids = meta.get(AGG_PDD_IDS_KEY) or []
    if not isinstance(pdd_ids, list):
        pdd_ids = []
    batch_log = meta.get(AGG_BATCH_LOG_KEY) or []
    if not isinstance(batch_log, list):
        batch_log = []
    return {
        "in_progress": bool(meta.get(AGG_IN_PROGRESS_KEY)),
        "finalized": bool(meta.get(AGG_FINALIZED_KEY)),
        "outcome": str(meta.get(AGG_OUTCOME_KEY) or ""),
        "accumulated_success_count": len([str(x).strip() for x in pdd_ids if str(x).strip()]),
        "batch_log": batch_log,
    }


def pipeline_to_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    from pdd_agent.api.services.pipeline_late_retry_policy import (
        build_late_retry_public_state,
        merge_late_retry_listing_statuses,
    )
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
        build_batch_limited_time_retry_public_state,
    )
    from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.bridge import (
        build_auto_retry_public_state,
    )
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_eligibility import (
        is_pipeline_initial_limited_time_phase_complete,
        is_pipeline_listing_batches_complete,
    )
    from pdd_agent.api.services.pipeline_per_batch_lt_chunks.bridge import (
        build_per_batch_lt_chunk_public_state,
    )

    per_batch_lt_chunk = build_per_batch_lt_chunk_public_state(row)

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
        "listing_only": bool((row.meta or {}).get("listing_only")),
        "continue_after_limited_time_failure": _pipeline_continue_after_limited_time_failure(row),
        "continue_after_activity_failure": _pipeline_continue_after_activity_failure(row),
        "promote_after_limited_time_failure": _pipeline_promote_after_limited_time_failure(row),
        "activity_limited_time_success_only": _pipeline_activity_limited_time_success_only(row),
        "activity_traffic_batch_enabled": bool((row.meta or {}).get("activity_traffic_batch_enabled")),
        "activity_traffic_batch_size": int((row.meta or {}).get("activity_traffic_batch_size") or 10),
        "activity_traffic_batch_display": str((row.meta or {}).get("activity_traffic_batch_display") or ""),
        "per_batch_limited_time_chunk_size": int(per_batch_lt_chunk.get("chunk_size") or 10),
        "per_batch_limited_time_chunk_enabled": bool(per_batch_lt_chunk.get("enabled")),
        "per_batch_limited_time_chunk_display": str(per_batch_lt_chunk.get("display") or ""),
        "per_batch_lt_chunk_supported": bool(per_batch_lt_chunk.get("supported")),
        "per_batch_lt_chunk_sequence_active": bool(per_batch_lt_chunk.get("sequence_active")),
        "activity_pdd_product_ids": list(
            (row.meta or {}).get("activity_pdd_product_ids")
            or (row.meta or {}).get("limited_time_success_pdd_product_ids")
            or []
        ),
        "limited_time_success_detail": str((row.meta or {}).get("limited_time_success_detail") or ""),
        "limited_time_outcome": str((row.meta or {}).get("limited_time_outcome") or ""),
        "limited_time_skip_reason": str((row.meta or {}).get("limited_time_skip_reason") or ""),
        "per_batch_lt_aggregate": _per_batch_lt_aggregate_public_state(row),
        "activity_delay_hours": float(row.activity_delay_hours or 24.0),
        "demo_mode": bool(row.demo_mode),
        "slot_alignment_test": bool((row.meta or {}).get("slot_alignment_test")),
        "spec_fill_verify_test": bool((row.meta or {}).get("spec_fill_verify_test")),
        "primary_style_first_test": bool((row.meta or {}).get("primary_style_first_test")),
        "paren_size_as_product_type": bool((row.meta or {}).get("paren_size_as_product_type")),
        "category_next_burst_demo": bool((row.meta or {}).get("category_next_burst_demo", True)),
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
        "listing_limited_time_phase_completed": bool(
            (row.meta or {}).get("listing_limited_time_phase_completed")
        ),
        "store_sequential": dict((row.meta or {}).get("store_sequential") or {}),
        "listing_unit_statuses": merge_late_retry_listing_statuses(
            row,
            build_listing_unit_statuses(row),
        ),
        "late_retry": build_late_retry_public_state(row),
        "batch_limited_time_retry": build_batch_limited_time_retry_public_state(row),
        "batch_limited_time_auto_retry": build_auto_retry_public_state(row),
        "listing_batches_complete": is_pipeline_listing_batches_complete(row),
        "initial_limited_time_phase_complete": is_pipeline_initial_limited_time_phase_complete(row),
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
    listing_only: bool = False,
    continue_after_limited_time_failure: bool = False,
    continue_after_activity_failure: bool = False,
    promote_after_limited_time_failure: bool = False,
    activity_delay_hours: float = 24.0,
    demo_mode: bool = False,
    platform_listing_code: str = "",
    slot_alignment_test: bool = False,
    spec_fill_verify_test: bool = False,
    primary_style_first_test: bool = False,
    paren_size_as_product_type: bool = False,
    category_next_burst_demo: bool = True,
    listing_scheduled_at: datetime | None = None,
    batch_id: str = "",
    skip_listing: bool = False,
    listing_skip_selectors: list[str] | None = None,
    material_source: str = "",
    use_minio_cache_only: bool = False,
    listing_input_mode: ListingInputMode = "selector",
    relist_strategy: str = "ignore",
    listing_throttle_enabled: bool = False,
    listing_batch_set_count: int = 5,
    listing_batch_interval_minutes: int = 30,
    listing_per_batch_limited_time_enabled: bool = False,
    listing_per_batch_campaign_enabled: bool = False,
    listing_per_batch_lt_traffic_activity_enabled: bool = False,
    listing_per_batch_promote_lt_success_only_enabled: bool = True,
    delist_spec_code_search_enabled: bool = False,
    activity_limited_time_success_only: bool = False,
    activity_traffic_batch_enabled: bool = False,
    activity_traffic_batch_size: int = 10,
    per_batch_limited_time_chunk_size: int = 10,
    batch_limited_time_auto_retry_enabled: bool = False,
    batch_limited_time_auto_retry_max_attempts: int = 1,
    extra_meta: dict[str, Any] | None = None,
    trigger_source: str = "manual",
    skip_commerce_gate: bool = False,
    commerce_intent_id: str = "",
) -> dict[str, Any]:
    account_id = str(account_id or "").strip()
    normalized_activity_ids = _normalize_pipeline_activity_ids(activity_id, activity_ids)
    from pdd_agent.api.services.pipeline_listing_only_mode import apply_listing_only_mode

    mode = apply_listing_only_mode(
        listing_only=bool(listing_only),
        activity_ids=normalized_activity_ids,
        auto_promotion=auto_promotion,
        auto_limited_time_setup=auto_limited_time_setup,
        continue_after_limited_time_failure=continue_after_limited_time_failure,
        continue_after_activity_failure=continue_after_activity_failure,
        promote_after_limited_time_failure=promote_after_limited_time_failure,
        activity_limited_time_success_only=activity_limited_time_success_only,
        listing_per_batch_limited_time_enabled=listing_per_batch_limited_time_enabled,
        listing_per_batch_campaign_enabled=listing_per_batch_campaign_enabled,
        listing_per_batch_lt_traffic_activity_enabled=listing_per_batch_lt_traffic_activity_enabled,
        listing_per_batch_promote_lt_success_only_enabled=listing_per_batch_promote_lt_success_only_enabled,
        activity_traffic_batch_enabled=activity_traffic_batch_enabled,
        batch_limited_time_auto_retry_enabled=batch_limited_time_auto_retry_enabled,
    )
    normalized_activity_ids = list(mode["activity_ids"])
    auto_promotion = bool(mode["auto_promotion"])
    auto_limited_time_setup = bool(mode["auto_limited_time_setup"])
    continue_after_limited_time_failure = bool(mode["continue_after_limited_time_failure"])
    continue_after_activity_failure = bool(mode["continue_after_activity_failure"])
    promote_after_limited_time_failure = bool(mode["promote_after_limited_time_failure"])
    activity_limited_time_success_only = bool(mode["activity_limited_time_success_only"])
    listing_per_batch_limited_time_enabled = bool(mode["listing_per_batch_limited_time_enabled"])
    listing_per_batch_campaign_enabled = bool(mode["listing_per_batch_campaign_enabled"])
    listing_per_batch_lt_traffic_activity_enabled = bool(mode["listing_per_batch_lt_traffic_activity_enabled"])
    listing_per_batch_promote_lt_success_only_enabled = bool(
        mode["listing_per_batch_promote_lt_success_only_enabled"]
    )
    activity_traffic_batch_enabled = bool(mode["activity_traffic_batch_enabled"])
    batch_limited_time_auto_retry_enabled = bool(mode["batch_limited_time_auto_retry_enabled"])
    activity_id = normalized_activity_ids[0] if normalized_activity_ids else ""
    if not account_id:
        raise ValueError("account_id is required")
    if not normalized_activity_ids and not listing_only:
        raise ValueError("activity_ids is required")
    if slot_alignment_test and spec_fill_verify_test:
        raise ValueError("spec_fill_verify_test 与 slot_alignment_test 不能同时开启")
    if listing_per_batch_lt_traffic_activity_enabled:
        if not listing_throttle_enabled:
            raise ValueError("分批「限时→推广→活动」须同时开启分批上架")
        if not listing_per_batch_limited_time_enabled:
            raise ValueError("分批「限时→推广→活动」须同时开启每批限时限量购")
        if listing_per_batch_campaign_enabled:
            raise ValueError("分批「限时→推广→活动」与「每批活动/推广」不能同时开启")
    if activity_traffic_batch_enabled:
        if listing_per_batch_lt_traffic_activity_enabled:
            raise ValueError("活动/推广分批与「分批：限时→推广→活动」不能同时开启")
        if listing_per_batch_campaign_enabled:
            raise ValueError("活动/推广分批与「每批活动/推广」不能同时开启")
        if not auto_promotion:
            raise ValueError("活动/推广分批须同时开启自动推广")

    from pdd_agent.api.services.pipeline_listing_throttle import (
        apply_throttle_to_listing_codes,
        build_listing_throttle_state,
        enqueue_listing_batch_for_pipeline,
    )
    from pdd_agent.api.services.pipeline_relist_strategy import (
        build_pipeline_listing_plan,
        enqueue_pipeline_relist_prep,
        normalize_relist_strategy,
        resolve_listing_flags_for_strategy,
        validate_relist_strategy_for_start,
    )

    strategy = normalize_relist_strategy(relist_strategy)
    validate_relist_strategy_for_start(strategy)
    skip_listing, skip_selectors = resolve_listing_flags_for_strategy(
        strategy,
        skip_listing=skip_listing,
        listing_skip_selectors=listing_skip_selectors,
    )

    codes, listing_input_meta = _resolve_pipeline_listing_codes(
        product_codes,
        listing_input_mode=listing_input_mode,
    )

    skip_selector_set = set(skip_selectors)
    list_codes = [c for c in codes if c not in skip_selector_set]

    if not skip_commerce_gate:
        from pdd_agent.api.services.commerce_dispatch import (
            build_pipeline_payload_from_kwargs,
            gate_integrated_pipeline_start,
        )

        pipeline_kwargs = build_pipeline_payload_from_kwargs(
            {
                "activity_id": activity_id,
                "activity_ids": normalized_activity_ids,
                "category_keyword": category_keyword,
                "auto_promotion": auto_promotion,
                "auto_limited_time_setup": auto_limited_time_setup,
                "listing_only": listing_only,
                "continue_after_limited_time_failure": continue_after_limited_time_failure,
                "continue_after_activity_failure": continue_after_activity_failure,
                "promote_after_limited_time_failure": promote_after_limited_time_failure,
                "activity_delay_hours": activity_delay_hours,
                "demo_mode": demo_mode,
                "platform_listing_code": platform_listing_code,
                "slot_alignment_test": slot_alignment_test,
                "spec_fill_verify_test": spec_fill_verify_test,
                "primary_style_first_test": primary_style_first_test,
                "paren_size_as_product_type": paren_size_as_product_type,
                "category_next_burst_demo": category_next_burst_demo,
                "listing_scheduled_at": listing_scheduled_at,
                "batch_id": batch_id,
                "skip_listing": skip_listing,
                "listing_skip_selectors": skip_selectors,
                "material_source": material_source,
                "use_minio_cache_only": bool(use_minio_cache_only),
                "listing_input_mode": listing_input_mode,
                "relist_strategy": strategy,
                "listing_throttle_enabled": listing_throttle_enabled,
                "listing_batch_set_count": listing_batch_set_count,
                "listing_batch_interval_minutes": listing_batch_interval_minutes,
                "listing_per_batch_limited_time_enabled": listing_per_batch_limited_time_enabled,
                "listing_per_batch_campaign_enabled": listing_per_batch_campaign_enabled,
                "listing_per_batch_lt_traffic_activity_enabled": listing_per_batch_lt_traffic_activity_enabled,
                "listing_per_batch_promote_lt_success_only_enabled": listing_per_batch_promote_lt_success_only_enabled,
                "delist_spec_code_search_enabled": delist_spec_code_search_enabled,
                "activity_limited_time_success_only": activity_limited_time_success_only,
                "activity_traffic_batch_enabled": activity_traffic_batch_enabled,
                "activity_traffic_batch_size": activity_traffic_batch_size,
                "per_batch_limited_time_chunk_size": per_batch_limited_time_chunk_size,
                "batch_limited_time_auto_retry_enabled": batch_limited_time_auto_retry_enabled,
                "batch_limited_time_auto_retry_max_attempts": batch_limited_time_auto_retry_max_attempts,
                "extra_meta": extra_meta,
                "trigger_source": trigger_source,
            }
        )
        queued = gate_integrated_pipeline_start(
            account_id=account_id,
            product_selectors=codes,
            trigger_source=trigger_source,
            pipeline_payload=pipeline_kwargs,
        )
        if queued:
            return queued

    pipeline_id = _pipeline_id()
    listing_run_id = create_listing_run(account_id)
    meta: dict[str, Any] = {
        "category_keyword": category_keyword,
        "platform_listing_code": platform_listing_code,
        "slot_alignment_test": bool(slot_alignment_test),
        "spec_fill_verify_test": bool(spec_fill_verify_test),
        "primary_style_first_test": bool(primary_style_first_test),
        "paren_size_as_product_type": bool(paren_size_as_product_type),
        "category_next_burst_demo": bool(category_next_burst_demo),
        "material_source": str(material_source or ""),
        "use_minio_cache_only": bool(use_minio_cache_only),
        "auto_limited_time_setup": bool(auto_limited_time_setup and normalized_activity_ids),
        "continue_after_limited_time_failure": bool(continue_after_limited_time_failure),
        "continue_after_activity_failure": bool(continue_after_activity_failure),
        "promote_after_limited_time_failure": bool(promote_after_limited_time_failure),
        "activity_limited_time_success_only": bool(activity_limited_time_success_only),
        "activity_ids": normalized_activity_ids,
        "campaign_activity_index": 0,
        "campaign_results": [],
        "relist_strategy": strategy,
        "delist_spec_code_search_enabled": bool(delist_spec_code_search_enabled),
        "commerce_trigger_source": str(trigger_source or "manual"),
        **listing_input_meta,
    }
    meta.update(dict(mode.get("meta_patch") or {}))
    if str(trigger_source or "") == "rabbitmq_auto":
        meta["mq_auto_deferred_phase2"] = True
    if batch_id:
        meta["batch_id"] = batch_id
    if extra_meta:
        meta.update(dict(extra_meta))
    from pdd_agent.api.services.pipeline_per_batch_limited_time import per_batch_limited_time_meta_patch

    meta.update(
        per_batch_limited_time_meta_patch(enabled=bool(listing_per_batch_limited_time_enabled))
    )
    from pdd_agent.api.services.pipeline_per_batch_campaign import per_batch_campaign_meta_patch

    meta.update(per_batch_campaign_meta_patch(enabled=bool(listing_per_batch_campaign_enabled)))
    from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.bridge import (
        per_batch_lt_traffic_activity_meta_patch,
        per_batch_promote_lt_success_only_meta_patch,
    )

    meta.update(
        per_batch_lt_traffic_activity_meta_patch(
            enabled=bool(listing_per_batch_lt_traffic_activity_enabled)
        )
    )
    if listing_per_batch_limited_time_enabled:
        meta.update(
            per_batch_promote_lt_success_only_meta_patch(
                enabled=bool(listing_per_batch_promote_lt_success_only_enabled)
            )
        )
    from pdd_agent.api.services.pipeline_per_batch_lt_chunks.bridge import (
        per_batch_lt_chunks_meta_patch,
    )

    if listing_per_batch_limited_time_enabled and not listing_per_batch_lt_traffic_activity_enabled:
        meta.update(
            per_batch_lt_chunks_meta_patch(
                chunk_size=int(per_batch_limited_time_chunk_size or 10),
                enabled=True,
            )
        )
    from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.bridge import (
        auto_retry_meta_patch,
    )

    if (
        listing_per_batch_limited_time_enabled
        and not listing_per_batch_lt_traffic_activity_enabled
        and not listing_per_batch_campaign_enabled
        and bool(batch_limited_time_auto_retry_enabled)
    ):
        meta.update(
            auto_retry_meta_patch(
                enabled=True,
                max_attempts=int(batch_limited_time_auto_retry_max_attempts or 1),
            )
        )
    from pdd_agent.api.services.pipeline_activity_traffic_batch.bridge import (
        activity_traffic_batch_meta_patch,
    )

    meta.update(
        activity_traffic_batch_meta_patch(
            enabled=bool(activity_traffic_batch_enabled),
            batch_size=int(activity_traffic_batch_size or 10),
        )
    )
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
        from pdd_agent.api.services.commerce_dispatch import register_integrated_pipeline_lifecycle

        register_integrated_pipeline_lifecycle(
            account_id=account_id,
            pipeline_id=pipeline_id,
            product_selectors=codes,
            trigger_source=trigger_source,
            intent_id=commerce_intent_id,
        )
    except Exception:
        logger.exception("register commerce lifecycle failed pipeline_id=%s", pipeline_id)
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

    listing_plan = build_pipeline_listing_plan(
        relist_strategy=strategy,
        account_id=account_id,
        selectors=codes,
        skip_listing=skip_listing,
        skip_selectors=skip_selectors,
        listing_payload_base={
            "category_keyword": category_keyword,
            "platform_listing_code": platform_listing_code,
            "slot_alignment_test": bool(slot_alignment_test),
            "spec_fill_verify_test": bool(spec_fill_verify_test),
            "primary_style_first_test": bool(primary_style_first_test),
            "paren_size_as_product_type": bool(paren_size_as_product_type),
            "category_next_burst_demo": bool(category_next_burst_demo),
            "material_source": str(material_source or ""),
            "use_minio_cache_only": bool(use_minio_cache_only),
        },
    )

    effective_listing_codes = listing_plan.listing_codes or listing_codes
    listing_payload_base = {
        "category_keyword": category_keyword,
        "platform_listing_code": platform_listing_code,
        "slot_alignment_test": bool(slot_alignment_test),
        "spec_fill_verify_test": bool(spec_fill_verify_test),
        "primary_style_first_test": bool(primary_style_first_test),
        "paren_size_as_product_type": bool(paren_size_as_product_type),
        "category_next_burst_demo": bool(category_next_burst_demo),
        "material_source": str(material_source or ""),
        "use_minio_cache_only": bool(use_minio_cache_only),
    }
    throttle_state = build_listing_throttle_state(
        effective_listing_codes,
        enabled=bool(listing_throttle_enabled),
        batch_set_count=listing_batch_set_count,
        interval_minutes=listing_batch_interval_minutes,
        listing_payload_base=listing_payload_base,
    )
    if throttle_state:
        meta["listing_throttle"] = throttle_state
        update_integrated_pipeline(pipeline_id, meta_patch={"listing_throttle": throttle_state})

    if listing_plan.action == "relist_prep":
        pending = dict(listing_plan.pending_listing or {})
        if throttle_state:
            pending["listing_throttle_enabled"] = True
        enqueue_pipeline_relist_prep(
            pipeline_id=pipeline_id,
            account_id=account_id,
            targets=listing_plan.relist_targets,
            pending_listing=pending,
        )
        logger.info(
            "integrated pipeline started with relist prep pipeline_id=%s account=%s targets=%s",
            pipeline_id,
            account_id,
            len(listing_plan.relist_targets),
        )
        refreshed = get_integrated_pipeline(pipeline_id)
        return pipeline_to_dict(refreshed or row)

    first_batch_codes = apply_throttle_to_listing_codes(effective_listing_codes, throttle_state)
    if throttle_state:
        enqueue_listing_batch_for_pipeline(
            pipeline_id=pipeline_id,
            account_id=account_id,
            batch_codes=first_batch_codes,
            listing_payload_base=listing_payload_base,
            scheduled_at=listing_scheduled_at or datetime.now(),
        )
        logger.info(
            "integrated pipeline started with throttled listing pipeline_id=%s batch=1/%s sets_per_batch=%s",
            pipeline_id,
            throttle_state.get("total_batches"),
            throttle_state.get("batch_set_count"),
        )
    else:
        enqueue_task(
            agent=AgentKind.LISTING.value,
            run_id=listing_run_id,
            account_id=account_id,
            payload={
                "product_codes": first_batch_codes,
                "dry_run": False,
                "category_keyword": category_keyword,
                "platform_listing_code": platform_listing_code,
                "pipeline_id": pipeline_id,
                "slot_alignment_test": bool(slot_alignment_test),
                "spec_fill_verify_test": bool(spec_fill_verify_test),
                "primary_style_first_test": bool(primary_style_first_test),
                "paren_size_as_product_type": bool(paren_size_as_product_type),
                "category_next_burst_demo": bool(category_next_burst_demo),
                "material_source": str(material_source or ""),
                "use_minio_cache_only": bool(use_minio_cache_only),
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


def _batch_run_item_from_start(
    data: dict[str, Any],
    *,
    scheduled_at: datetime,
) -> dict[str, Any]:
    """将 start_integrated_pipeline 返回值转为批量项；支持 commerce_queued。"""
    if data.get("commerce_queued"):
        return {
            "account_id": str(data.get("account_id") or ""),
            "pipeline_id": "",
            "listing_run_id": "",
            "listing_scheduled_at": scheduled_at,
            "commerce_queued": True,
            "intent_id": str(data.get("intent_id") or ""),
            "block_reason": str(data.get("block_reason") or ""),
            "block_reason_label": str(data.get("block_reason_label") or ""),
            "wake_at": str(data.get("wake_at") or ""),
            "is_merged": bool(data.get("is_merged")),
        }
    return {
        "account_id": str(data.get("account_id") or ""),
        "pipeline_id": str(data.get("pipeline_id") or ""),
        "listing_run_id": str(data.get("listing_run_id") or ""),
        "listing_scheduled_at": scheduled_at,
        "commerce_queued": False,
    }


def _build_batch_commerce_queued_response(
    *,
    batch_id: str,
    items: list[dict[str, Any]],
    queued: dict[str, Any],
    max_concurrent: int,
    delay_range: tuple[int, int],
    store_sequential_enabled: bool,
    pending_stores: int = 0,
) -> dict[str, Any]:
    reason_label = str(queued.get("block_reason_label") or "").strip()
    account_id = str(queued.get("account_id") or "")
    return {
        "batch_id": batch_id,
        "total": len(items),
        "max_concurrent_stores": max_concurrent,
        "store_start_delay_min_seconds": delay_range[0],
        "store_start_delay_max_seconds": delay_range[1],
        "store_sequential_enabled": store_sequential_enabled,
        "pending_stores": pending_stores,
        "pipelines": [],
        "commerce_queued": True,
        "queued_count": 1,
        "intent_id": str(queued.get("intent_id") or ""),
        "account_id": account_id,
        "block_reason": str(queued.get("block_reason") or ""),
        "block_reason_label": reason_label,
        "wake_at": str(queued.get("wake_at") or ""),
        "is_merged": bool(queued.get("is_merged")),
        "message": reason_label
        or f"店铺 {account_id} 任务已排队，当前有进行中的运营周期",
    }


def start_integrated_pipeline_batch(
    *,
    items: list[dict[str, Any]],
    activity_id: str = "",
    activity_ids: list[str] | None = None,
    category_keyword: str = "玩偶",
    auto_promotion: bool = True,
    auto_limited_time_setup: bool = True,
    listing_only: bool = False,
    continue_after_limited_time_failure: bool = False,
    continue_after_activity_failure: bool = False,
    promote_after_limited_time_failure: bool = False,
    activity_delay_hours: float = 24.0,
    demo_mode: bool = False,
    platform_listing_code: str = "",
    slot_alignment_test: bool = False,
    spec_fill_verify_test: bool = False,
    primary_style_first_test: bool = False,
    paren_size_as_product_type: bool = False,
    category_next_burst_demo: bool = True,
    store_start_delay_min_seconds: int | None = None,
    store_start_delay_max_seconds: int | None = None,
    max_concurrent_stores: int | None = None,
    skip_listing: bool = False,
    listing_skip_selectors: list[str] | None = None,
    material_source: str = "",
    use_minio_cache_only: bool = False,
    relist_strategy: str = "ignore",
    listing_throttle_enabled: bool = False,
    listing_batch_set_count: int = 5,
    listing_batch_interval_minutes: int = 30,
    listing_per_batch_limited_time_enabled: bool = False,
    listing_per_batch_campaign_enabled: bool = False,
    listing_per_batch_lt_traffic_activity_enabled: bool = False,
    listing_per_batch_promote_lt_success_only_enabled: bool = True,
    store_sequential_enabled: bool = False,
    delist_spec_code_search_enabled: bool = False,
    activity_limited_time_success_only: bool = False,
    activity_traffic_batch_enabled: bool = False,
    activity_traffic_batch_size: int = 10,
    per_batch_limited_time_chunk_size: int = 10,
    batch_limited_time_auto_retry_enabled: bool = False,
    batch_limited_time_auto_retry_max_attempts: int = 1,
    trigger_source: str = "manual",
) -> dict[str, Any]:
    """批量创建整合链路；默认各店按启动间隔错开并行入队；串行模式下一家跑完再跑下一家。"""
    from pdd_agent.api.services.pipeline_store_sequential import (
        build_coordinator_sequential_meta,
        build_store_sequential_common_params,
    )

    normalized_activity_ids = _normalize_pipeline_activity_ids(activity_id, activity_ids)
    activity_id = normalized_activity_ids[0] if normalized_activity_ids else ""
    if not normalized_activity_ids and not listing_only:
        raise ValueError("activity_ids is required")
    if not items:
        raise ValueError("items is required")

    batch_id = _batch_id()
    delay_range = resolve_batch_delay(store_start_delay_min_seconds, store_start_delay_max_seconds)
    max_concurrent = 1 if store_sequential_enabled else resolve_batch_concurrency(max_concurrent_stores)
    scheduled_at = datetime.now()
    pipelines: list[dict[str, Any]] = []

    common_params = build_store_sequential_common_params(
        activity_id=activity_id,
        activity_ids=normalized_activity_ids,
        category_keyword=category_keyword,
        auto_promotion=auto_promotion,
        auto_limited_time_setup=auto_limited_time_setup,
        listing_only=listing_only,
        continue_after_limited_time_failure=continue_after_limited_time_failure,
        continue_after_activity_failure=continue_after_activity_failure,
        promote_after_limited_time_failure=promote_after_limited_time_failure,
        activity_delay_hours=activity_delay_hours,
        demo_mode=demo_mode,
        platform_listing_code=platform_listing_code,
        slot_alignment_test=slot_alignment_test,
        spec_fill_verify_test=spec_fill_verify_test,
        primary_style_first_test=primary_style_first_test,
        paren_size_as_product_type=paren_size_as_product_type,
        category_next_burst_demo=category_next_burst_demo,
        skip_listing=skip_listing,
        listing_skip_selectors=listing_skip_selectors,
        material_source=material_source,
        use_minio_cache_only=use_minio_cache_only,
        relist_strategy=relist_strategy,
        listing_throttle_enabled=listing_throttle_enabled,
        listing_batch_set_count=listing_batch_set_count,
        listing_batch_interval_minutes=listing_batch_interval_minutes,
        listing_per_batch_limited_time_enabled=listing_per_batch_limited_time_enabled,
        listing_per_batch_campaign_enabled=listing_per_batch_campaign_enabled,
        listing_per_batch_lt_traffic_activity_enabled=listing_per_batch_lt_traffic_activity_enabled,
        listing_per_batch_promote_lt_success_only_enabled=listing_per_batch_promote_lt_success_only_enabled,
        delist_spec_code_search_enabled=delist_spec_code_search_enabled,
        activity_limited_time_success_only=activity_limited_time_success_only,
        activity_traffic_batch_enabled=activity_traffic_batch_enabled,
        activity_traffic_batch_size=activity_traffic_batch_size,
        per_batch_limited_time_chunk_size=per_batch_limited_time_chunk_size,
        batch_limited_time_auto_retry_enabled=batch_limited_time_auto_retry_enabled,
        batch_limited_time_auto_retry_max_attempts=batch_limited_time_auto_retry_max_attempts,
        trigger_source=trigger_source,
    )

    if store_sequential_enabled:
        if len(items) < 2:
            raise ValueError("店铺串行模式至少需要选择 2 家店铺")
        first_item = items[0]
        pending_items = items[1:]
        data = start_integrated_pipeline(
            account_id=str(first_item.get("account_id") or "").strip(),
            product_codes=list(first_item.get("product_codes") or []),
            listing_scheduled_at=scheduled_at,
            batch_id=batch_id,
            extra_meta=build_coordinator_sequential_meta(
                pending_items=pending_items,
                common_params=common_params,
                delay_min_seconds=delay_range[0],
                delay_max_seconds=delay_range[1],
                total_stores=len(items),
                active_pipeline_id="",
            ),
            **common_params,
        )
        if data.get("commerce_queued"):
            return _build_batch_commerce_queued_response(
                batch_id=batch_id,
                items=items,
                queued=data,
                max_concurrent=max_concurrent,
                delay_range=delay_range,
                store_sequential_enabled=True,
                pending_stores=len(pending_items),
            )
        coordinator_id = str(data.get("pipeline_id") or "").strip()
        if coordinator_id:
            coordinator_row = get_integrated_pipeline(coordinator_id)
            seq = dict((coordinator_row.meta or {}).get("store_sequential") or {})
            seq["active_pipeline_id"] = coordinator_id
            seq["started_pipeline_ids"] = [coordinator_id]
            update_integrated_pipeline(coordinator_id, meta_patch={"store_sequential": seq})
        pipelines.append(
            _batch_run_item_from_start(data, scheduled_at=scheduled_at)
        )
        return {
            "batch_id": batch_id,
            "total": len(items),
            "max_concurrent_stores": max_concurrent,
            "store_start_delay_min_seconds": delay_range[0],
            "store_start_delay_max_seconds": delay_range[1],
            "store_sequential_enabled": True,
            "pending_stores": len(pending_items),
            "pipelines": pipelines,
            "message": (
                f"batch integrated pipeline queued sequentially: {len(items)} stores, "
                f"first store started, inter-store delay {delay_range[0]}-{delay_range[1]}s"
            ),
        }

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
            listing_only=listing_only,
            continue_after_limited_time_failure=continue_after_limited_time_failure,
            continue_after_activity_failure=continue_after_activity_failure,
            promote_after_limited_time_failure=promote_after_limited_time_failure,
            activity_delay_hours=activity_delay_hours,
            demo_mode=demo_mode,
            platform_listing_code=platform_listing_code,
            slot_alignment_test=slot_alignment_test,
            spec_fill_verify_test=spec_fill_verify_test,
            primary_style_first_test=primary_style_first_test,
            paren_size_as_product_type=paren_size_as_product_type,
            category_next_burst_demo=category_next_burst_demo,
            listing_scheduled_at=scheduled_at,
            batch_id=batch_id,
            skip_listing=skip_listing,
            listing_skip_selectors=listing_skip_selectors,
            material_source=material_source,
            use_minio_cache_only=use_minio_cache_only,
            relist_strategy=relist_strategy,
            listing_throttle_enabled=listing_throttle_enabled,
            listing_batch_set_count=listing_batch_set_count,
            listing_batch_interval_minutes=listing_batch_interval_minutes,
            listing_per_batch_limited_time_enabled=listing_per_batch_limited_time_enabled,
            listing_per_batch_campaign_enabled=listing_per_batch_campaign_enabled,
            listing_per_batch_lt_traffic_activity_enabled=listing_per_batch_lt_traffic_activity_enabled,
            listing_per_batch_promote_lt_success_only_enabled=listing_per_batch_promote_lt_success_only_enabled,
            delist_spec_code_search_enabled=delist_spec_code_search_enabled,
            activity_limited_time_success_only=activity_limited_time_success_only,
            activity_traffic_batch_enabled=activity_traffic_batch_enabled,
            activity_traffic_batch_size=activity_traffic_batch_size,
            per_batch_limited_time_chunk_size=per_batch_limited_time_chunk_size,
            batch_limited_time_auto_retry_enabled=batch_limited_time_auto_retry_enabled,
            batch_limited_time_auto_retry_max_attempts=batch_limited_time_auto_retry_max_attempts,
        )
        pipelines.append(
            _batch_run_item_from_start(data, scheduled_at=scheduled_at)
        )

    queued_count = sum(1 for row in pipelines if row.get("commerce_queued"))
    started = [row for row in pipelines if not row.get("commerce_queued")]
    if queued_count and not started:
        first_queued = next(row for row in pipelines if row.get("commerce_queued"))
        return _build_batch_commerce_queued_response(
            batch_id=batch_id,
            items=items,
            queued=first_queued,
            max_concurrent=max_concurrent,
            delay_range=delay_range,
            store_sequential_enabled=False,
            pending_stores=0,
        )

    return {
        "batch_id": batch_id,
        "total": len(pipelines),
        "max_concurrent_stores": max_concurrent,
        "store_start_delay_min_seconds": delay_range[0],
        "store_start_delay_max_seconds": delay_range[1],
        "store_sequential_enabled": False,
        "pending_stores": 0,
        "pipelines": pipelines,
        "commerce_queued": queued_count > 0,
        "queued_count": queued_count,
        "message": (
            f"batch integrated pipeline queued: {len(started)} started, "
            f"{queued_count} commerce-queued, concurrency {max_concurrent}, "
            f"start delay {delay_range[0]}-{delay_range[1]}s"
            if queued_count
            else (
                f"batch integrated pipeline queued: {len(pipelines)} pipelines, "
                f"concurrency {max_concurrent}, start delay {delay_range[0]}-{delay_range[1]}s"
            )
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

    result = result if isinstance(result, dict) else {}
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
        dispatch_batch_limited_time_retry_queue_task_finished,
    )

    batch_lt_retry_handled = dispatch_batch_limited_time_retry_queue_task_finished(
        row,
        agent=agent,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )
    if batch_lt_retry_handled:
        from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.bridge import (
            maybe_auto_start_for_pipeline_id,
        )

        maybe_auto_start_for_pipeline_id(
            pipeline_id,
            reason="after_batch_limited_time_retry_finished",
        )
        return

    from pdd_agent.api.services.failure_log_attach_retry.bridge import (
        dispatch_attach_retry_queue_task_finished,
    )

    if dispatch_attach_retry_queue_task_finished(
        row,
        agent=agent,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    ):
        return

    if row.status in TERMINAL_PIPELINE_STATUSES and not _should_process_queue_task_on_terminal_pipeline(
        row,
        agent=agent,
        run_id=run_id,
    ):
        return

    if _should_process_queue_task_on_terminal_pipeline(row, agent=agent, run_id=run_id):
        update_integrated_pipeline(
            row.pipeline_id,
            status="running",
            error="",
        )
        row = get_integrated_pipeline(row.pipeline_id) or row

    from pdd_agent.api.services.pipeline_late_retry_policy import dispatch_late_retry_queue_task_finished

    late_retry_handled = dispatch_late_retry_queue_task_finished(
        row,
        agent=agent,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )
    if not late_retry_handled:
        if agent == AgentKind.LISTING.value:
            _on_listing_finished(row, run_id=run_id, success=success, result=result, error=error)
        elif agent == AgentKind.CAMPAIGN.value:
            if _pipeline_limited_time_run_id(row) == run_id:
                _on_limited_time_finished(row, run_id=run_id, success=success, result=result, error=error)
            else:
                _on_campaign_finished(row, run_id=run_id, success=success, result=result, error=error)
        elif agent == AgentKind.TRAFFIC.value:
            _on_traffic_finished(row, run_id=run_id, success=success, error=error)
        elif agent == AgentKind.DELIST.value:
            from pdd_agent.api.services.pipeline_relist_strategy import handle_pipeline_delist_task_finished

            if handle_pipeline_delist_task_finished(
                pipeline_id=pipeline_id,
                run_id=run_id,
                success=success,
                result=result,
                error=error,
            ):
                return

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

    if late_retry_handled:
        refreshed = get_integrated_pipeline(pipeline_id)
        if refreshed and refreshed.status in TERMINAL_PIPELINE_STATUSES:
            try:
                from pdd_agent.api.services.pipeline_store_sequential import maybe_advance_sequential_store

                maybe_advance_sequential_store(refreshed)
            except Exception:
                logger.exception("advance sequential store failed pipeline_id=%s", pipeline_id)
        return

    _ensure_pipeline_failed_after_task(
        pipeline_id=pipeline_id,
        agent=agent,
        run_id=run_id,
        success=success,
        error=error,
        result=result,
    )

    refreshed = get_integrated_pipeline(pipeline_id)
    if refreshed and refreshed.status in TERMINAL_PIPELINE_STATUSES:
        try:
            from pdd_agent.api.services.pipeline_store_sequential import maybe_advance_sequential_store

            maybe_advance_sequential_store(refreshed)
        except Exception:
            logger.exception("advance sequential store failed pipeline_id=%s", pipeline_id)


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


def _continue_pipeline_after_listing(
    row,
    *,
    run_id: str,
    result: dict[str, Any],
    pdd_ids: list[str],
    mapping_ids: list[str],
    error_hint: str = "",
) -> bool:
    """
    用当前批 + 分批累计的成功商品继续限时限量/活动；有商品可继续时返回 True。
    单套/单批失败不阻断其余已成功商品及后续批次。
    """
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    pdd_ids, mapping_ids, missing = _merge_skipped_listing_products(
        refreshed,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    )
    if missing:
        return False

    from pdd_agent.api.services.pipeline_listing_throttle import (
        has_more_listing_batches,
        resolve_listing_products_after_batches,
        schedule_next_listing_batch_after_finish,
    )
    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        maybe_run_per_batch_limited_time_after_listing,
    )
    from pdd_agent.api.services.pipeline_per_batch_campaign import (
        maybe_run_per_batch_campaign_after_listing,
    )

    listing_meta = {
        "listing_summary": _summarize_run_message(run_id),
    }
    listing_meta.update(_listing_failure_meta(result))
    throttle_for_units = dict((refreshed.meta or {}).get("listing_throttle") or {})
    if throttle_for_units.get("enabled"):
        from pdd_agent.api.services.pipeline_listing_throttle import merge_unit_results_into_throttle

        listing_meta["listing_throttle"] = merge_unit_results_into_throttle(throttle_for_units, result)
    if error_hint:
        listing_meta["listing_batch_last_error"] = error_hint
        if not listing_meta.get("listing_outcome"):
            listing_meta["listing_outcome"] = LISTING_PARTIAL_OUTCOME

    if maybe_run_per_batch_limited_time_after_listing(
        refreshed,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        listing_meta=listing_meta,
    ):
        from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
            maybe_record_listing_batch as maybe_record_std_agg_listing_batch,
        )
        from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.bridge import (
            maybe_record_listing_batch,
        )

        record_row = get_integrated_pipeline(refreshed.pipeline_id) or refreshed
        maybe_record_listing_batch(
            record_row,
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
            listing_result=result,
        )
        maybe_record_std_agg_listing_batch(
            record_row,
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
            listing_result=result,
        )
        from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.bridge import (
            maybe_auto_start_batch_limited_time_retries,
        )

        maybe_auto_start_batch_limited_time_retries(
            get_integrated_pipeline(refreshed.pipeline_id) or record_row,
            reason="after_listing_triggered_per_batch_limited_time",
        )
        return True

    if maybe_run_per_batch_campaign_after_listing(
        refreshed,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        listing_meta=listing_meta,
    ):
        return True

    if schedule_next_listing_batch_after_finish(
        refreshed,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        listing_meta=listing_meta,
    ):
        logger.info(
            "pipeline %s listing batch finished, next batch scheduled run_id=%s",
            row.pipeline_id,
            run_id,
        )
        return True

    pdd_ids, mapping_ids = resolve_listing_products_after_batches(refreshed, pdd_ids, mapping_ids)
    if not pdd_ids:
        return False

    refreshed = get_integrated_pipeline(row.pipeline_id) or refreshed
    throttle = dict((refreshed.meta or {}).get("listing_throttle") or {})
    if throttle.get("enabled") and not has_more_listing_batches(throttle):
        listing_meta["listing_throttle"] = {**throttle, "completed": True}

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
            "pipeline %s listing done (partial ok), limited time scheduled at %s pdd_ids=%s",
            row.pipeline_id,
            limited_time_at,
            pdd_ids,
        )
        return True

    from pdd_agent.api.services.pipeline_listing_only_mode import is_listing_only_pipeline

    if is_listing_only_pipeline(refreshed):
        listing_meta["listing_limited_time_phase_completed"] = True
        update_integrated_pipeline(
            row.pipeline_id,
            status="completed",
            current_step="completed",
            pdd_product_ids=pdd_ids,
            mapping_ids=mapping_ids,
            meta_patch=listing_meta,
        )
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        _try_advance_store_sequential_after_listing_limited_time(refreshed)
        logger.info("pipeline %s listing-only completed pdd_ids=%s", row.pipeline_id, pdd_ids)
        return True

    scheduled_at = resolve_activity_scheduled_at(
        demo_mode=bool(refreshed.demo_mode),
        activity_delay_hours=float(refreshed.activity_delay_hours or 24.0),
    )
    base_at = datetime.now() + _resolve_activity_delay(
        demo_mode=bool(refreshed.demo_mode),
        activity_delay_hours=float(refreshed.activity_delay_hours or 24.0),
    )
    activity_jitter_seconds = max(0, int((scheduled_at - base_at).total_seconds()))
    listing_meta["activity_jitter_seconds"] = activity_jitter_seconds
    _schedule_pipeline_campaign(
        refreshed,
        activity_index=0,
        scheduled_at=scheduled_at,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        meta_patch=listing_meta,
    )
    logger.info(
        "pipeline %s listing done (partial ok), activity scheduled at %s pdd_ids=%s",
        row.pipeline_id,
        scheduled_at,
        pdd_ids,
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    _try_advance_store_sequential_after_listing_limited_time(refreshed)
    return True


def _on_listing_finished(row, *, run_id: str, success: bool, result: dict[str, Any], error: str) -> None:
    from pdd_agent.api.services.pipeline_listing_batch_continue import (
        has_remaining_listing_batch,
        maybe_continue_listing_batch_after_failure,
    )

    if not success:
        if maybe_continue_listing_batch_after_failure(
            row,
            run_id=run_id,
            result=result,
            error=error,
        ):
            return
        pdd_ids, mapping_ids = _extract_listing_products(result)
        if _continue_pipeline_after_listing(
            row,
            run_id=run_id,
            result=result,
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
            error_hint=error or "上架失败",
        ):
            logger.info(
                "pipeline %s listing batch failed but continuing with accumulated products run_id=%s",
                row.pipeline_id,
                run_id,
            )
            return
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
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        if has_remaining_listing_batch(refreshed) and maybe_continue_listing_batch_after_failure(
            refreshed,
            run_id=run_id,
            result=result,
            error=error or "本批无成功上架商品",
        ):
            logger.info(
                "pipeline %s listing batch finished with no pdd_ids, scheduled next batch run_id=%s",
                row.pipeline_id,
                run_id,
            )
            return
        if _continue_pipeline_after_listing(
            row,
            run_id=run_id,
            result=result,
            pdd_ids=[],
            mapping_ids=[],
            error_hint=error or "本批无成功上架商品",
        ):
            logger.info(
                "pipeline %s listing batch empty but continuing with accumulated products run_id=%s",
                row.pipeline_id,
                run_id,
            )
            return
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

    if _continue_pipeline_after_listing(
        row,
        run_id=run_id,
        result=result,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    ):
        return

    err = "上架完成但未获取到拼多多商品 ID"
    update_integrated_pipeline(
        row.pipeline_id,
        status="failed",
        current_step="listing_failed",
        error=err,
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
    from pdd_agent.api.services.pipeline_per_batch_campaign import maybe_continue_after_per_batch_campaign

    if maybe_continue_after_per_batch_campaign(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    ):
        return

    from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.bridge import (
        maybe_handle_campaign_finished as maybe_handle_ltta_campaign_finished,
    )

    if maybe_handle_ltta_campaign_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    ):
        return

    from pdd_agent.api.services.pipeline_activity_traffic_batch.bridge import (
        maybe_handle_campaign_finished as maybe_handle_activity_traffic_batch_campaign,
    )

    if maybe_handle_activity_traffic_batch_campaign(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    ):
        return

    if _campaign_run_already_handled(row, run_id):
        logger.debug(
            "skip duplicate campaign finished pipeline=%s run_id=%s",
            row.pipeline_id,
            run_id,
        )
        return

    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        maybe_record_campaign_finished,
    )

    maybe_record_campaign_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )

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
        from pdd_agent.api.services.pipeline_mq_auto_phase2 import maybe_complete_mq_phase2

        maybe_complete_mq_phase2(get_integrated_pipeline(row.pipeline_id) or row)
        return

    _enqueue_pipeline_traffic(refreshed, meta_patch=meta_patch)


def _on_limited_time_finished(row, *, run_id: str, success: bool, result: dict[str, Any], error: str) -> None:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        handle_pipeline_limited_time_finished_for_activity,
        is_activity_limited_time_success_only_row,
    )
    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        _per_batch_batch_log_context,
        maybe_continue_after_per_batch_limited_time,
        prepare_pipeline_row_for_post_listing_steps,
    )
    from pdd_agent.api.services.pipeline_per_batch_campaign import (
        maybe_start_per_batch_campaign_after_limited_time,
    )

    logger.info(
        "pipeline %s limited_time finished enter run_id=%s success=%s error=%s ctx=%s",
        row.pipeline_id,
        str(run_id or "").strip(),
        success,
        str(error or "").strip()[:200],
        _per_batch_batch_log_context(row),
    )

    from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.bridge import (
        maybe_handle_limited_time_finished as maybe_handle_ltta_limited_time_finished,
    )

    if maybe_handle_ltta_limited_time_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    ):
        logger.info(
            "pipeline %s limited_time finished handled by per-batch ltta run_id=%s",
            row.pipeline_id,
            run_id,
        )
        return

    if maybe_start_per_batch_campaign_after_limited_time(
        row,
        run_id=run_id,
        success=success,
        error=error,
    ):
        logger.info(
            "pipeline %s limited_time finished handled by per-batch campaign run_id=%s",
            row.pipeline_id,
            run_id,
        )
        return

    from pdd_agent.api.services.pipeline_per_batch_lt_chunks.bridge import (
        maybe_handle_limited_time_chunk_finished,
    )

    if maybe_handle_limited_time_chunk_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    ):
        logger.info(
            "pipeline %s limited_time finished handled by per-batch LT chunk run_id=%s",
            row.pipeline_id,
            run_id,
        )
        return

    from pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy import (
        accumulate_per_batch_limited_time_success,
    )

    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        record_limited_time_batch_finished as record_std_agg_limited_time_batch,
        restore_intermediate_lt_progress_meta,
    )

    row = record_std_agg_limited_time_batch(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )

    row = accumulate_per_batch_limited_time_success(row, run_id=run_id, result=result) or row

    if maybe_continue_after_per_batch_limited_time(
        row,
        run_id=run_id,
        success=success,
        error=error,
    ):
        restore_intermediate_lt_progress_meta(get_integrated_pipeline(row.pipeline_id) or row)
        logger.info(
            "pipeline %s limited_time finished handled by per-batch continue run_id=%s ctx=%s",
            row.pipeline_id,
            run_id,
            _per_batch_batch_log_context(get_integrated_pipeline(row.pipeline_id) or row),
        )
        from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.bridge import (
            maybe_auto_start_batch_limited_time_retries,
        )

        maybe_auto_start_batch_limited_time_retries(
            get_integrated_pipeline(row.pipeline_id) or row,
            reason="after_per_batch_limited_time_continue",
        )
        return

    from pdd_agent.api.services.pipeline_mq_auto_phase2 import handle_mq_auto_limited_time_finished

    if handle_mq_auto_limited_time_finished(
        row,
        run_id=run_id,
        success=success,
        error=error or "",
        advance_store_sequential_fn=_try_advance_store_sequential_after_listing_limited_time,
    ):
        return

    from pdd_agent.api.services.pipeline_lt_middle_batch_success_only_policy import (
        maybe_handle_middle_batch_before_success_only_finish,
    )

    if maybe_handle_middle_batch_before_success_only_finish(
        row,
        run_id=run_id,
        success=success,
        error=error,
    ):
        logger.info(
            "pipeline %s limited_time finished handled by middle-batch policy run_id=%s ctx=%s",
            row.pipeline_id,
            run_id,
            _per_batch_batch_log_context(get_integrated_pipeline(row.pipeline_id) or row),
        )
        return

    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        maybe_finalize_after_all_batches as maybe_finalize_std_agg_limited_time,
    )

    if maybe_finalize_std_agg_limited_time(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
        schedule_activity_fn=_schedule_pipeline_activity_after_limited_time,
        advance_store_sequential_fn=_try_advance_store_sequential_after_listing_limited_time,
        summarize_run_message_fn=_summarize_run_message,
    ):
        logger.info(
            "pipeline %s limited_time finished handled by std per-batch LT aggregate run_id=%s",
            row.pipeline_id,
            run_id,
        )
        from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.bridge import (
            maybe_auto_start_batch_limited_time_retries,
        )

        maybe_auto_start_batch_limited_time_retries(
            get_integrated_pipeline(row.pipeline_id) or row,
            reason="after_std_per_batch_lt_aggregate_finalize",
        )
        return

    if is_activity_limited_time_success_only_row(row):
        from pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy import (
            maybe_finalize_limited_time_success_only_with_accumulation,
        )

        if maybe_finalize_limited_time_success_only_with_accumulation(
            row,
            run_id=run_id,
            success=success,
            result=result,
            error=error,
            schedule_activity_fn=_schedule_pipeline_activity_after_limited_time,
            advance_store_sequential_fn=_try_advance_store_sequential_after_listing_limited_time,
        ):
            return
        if handle_pipeline_limited_time_finished_for_activity(
            row,
            run_id=run_id,
            success=success,
            result=result,
            error=error,
            schedule_activity_fn=_schedule_pipeline_activity_after_limited_time,
            advance_store_sequential_fn=_try_advance_store_sequential_after_listing_limited_time,
        ):
            return

    row = prepare_pipeline_row_for_post_listing_steps(row) or row
    meta = dict(row.meta or {})
    activity_already_scheduled = bool(
        getattr(row, "campaign_run_id", None) or getattr(row, "scheduled_activity_at", None)
    )
    if meta.get("limited_time_finish_handled") and activity_already_scheduled:
        return
    if meta.get("limited_time_finish_handled") and not activity_already_scheduled:
        logger.warning(
            "pipeline %s stale limited_time_finish_handled without activity, rescheduling",
            row.pipeline_id,
        )
    meta_patch: dict[str, Any] = {
        "limited_time_finish_handled": True,
        "limited_time_summary": _summarize_run_message(run_id),
    }
    if not success:
        meta_patch["limited_time_outcome"] = "failed"
        failure_message = error or "限时限量购设置失败"
        from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
            should_absorb_per_batch_limited_time_failure,
        )

        if should_absorb_per_batch_limited_time_failure(row, run_id=run_id):
            from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
                build_per_batch_limited_time_failure_meta,
                has_pending_throttled_listing_batches,
                is_per_batch_limited_time_pipeline,
                log_absorbed_limited_time_failure,
            )

            meta_patch.update(build_per_batch_limited_time_failure_meta(failure_message))
            refreshed = get_integrated_pipeline(row.pipeline_id) or row
            if is_per_batch_limited_time_pipeline(refreshed) and has_pending_throttled_listing_batches(
                refreshed
            ):
                if maybe_continue_after_per_batch_limited_time(
                    refreshed,
                    run_id=run_id,
                    success=False,
                    error=failure_message,
                ):
                    log_absorbed_limited_time_failure(
                        refreshed, run_id=run_id, error=failure_message
                    )
                    return
                log_absorbed_limited_time_failure(
                    refreshed, run_id=run_id, error=failure_message
                )
                update_integrated_pipeline(
                    row.pipeline_id,
                    status="running",
                    current_step="waiting_limited_time_per_batch",
                    error="",
                    meta_patch=meta_patch,
                )
                logger.warning(
                    "pipeline %s per-batch limited time failed mid-batch but next listing batch not scheduled",
                    row.pipeline_id,
                )
                return
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
        from pdd_agent.api.services.pipeline_lt_failure_promotion_policy import (
            maybe_lt_failure_skip_activity_and_enqueue_promotion,
        )

        if maybe_lt_failure_skip_activity_and_enqueue_promotion(
            row,
            run_id=run_id,
            success=success,
            result=result,
            error=failure_message,
            enqueue_traffic_fn=_enqueue_pipeline_traffic,
            advance_store_sequential_fn=_try_advance_store_sequential_after_listing_limited_time,
            summarize_run_message_fn=_summarize_run_message,
        ):
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
    from pdd_agent.api.services.pipeline_per_batch_campaign import maybe_continue_after_per_batch_traffic

    if maybe_continue_after_per_batch_traffic(
        row,
        run_id=run_id,
        success=success,
        error=error,
    ):
        return

    from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.bridge import (
        maybe_handle_traffic_finished as maybe_handle_ltta_traffic_finished,
    )

    if maybe_handle_ltta_traffic_finished(
        row,
        run_id=run_id,
        success=success,
        error=error,
    ):
        return

    from pdd_agent.api.services.pipeline_activity_traffic_batch.bridge import (
        maybe_handle_traffic_finished as maybe_handle_activity_traffic_batch_traffic,
    )

    if maybe_handle_activity_traffic_batch_traffic(
        row,
        run_id=run_id,
        success=success,
        error=error,
    ):
        return

    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        maybe_record_traffic_finished,
    )

    maybe_record_traffic_finished(
        row,
        run_id=run_id,
        success=success,
        error=error,
    )

    meta = dict(row.meta or {})
    if meta.get("traffic_finish_handled"):
        logger.debug(
            "skip duplicate traffic finished pipeline=%s run_id=%s",
            row.pipeline_id,
            run_id,
        )
        return
    if not success:
        from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
            should_absorb_traffic_failure_after_batch_lt_revive,
        )

        if should_absorb_traffic_failure_after_batch_lt_revive(row, run_id):
            logger.info(
                "pipeline %s absorb stale traffic failure after batch lt revive run_id=%s",
                row.pipeline_id,
                run_id,
            )
            return
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
    from pdd_agent.api.services.pipeline_mq_auto_phase2 import maybe_complete_mq_phase2_on_traffic_finished

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    maybe_complete_mq_phase2_on_traffic_finished(refreshed)


def _run_status_value(status) -> str:
    if status is None:
        return ""
    return str(status.value if hasattr(status, "value") else status)


def _listing_batches_complete_for_activity(row) -> bool:
    """分批上架尚未结束时不要预约全量活动。"""
    from pdd_agent.api.services.pipeline_listing_batch_continue import has_remaining_listing_batch
    from pdd_agent.api.services.pipeline_per_batch_limited_time import _per_batch_state

    if has_remaining_listing_batch(row):
        return False
    step = str(row.current_step or "")
    if step.startswith("waiting_listing_batch_"):
        return False
    if dict(_per_batch_state(row)).get("pending"):
        return False
    return True


def _reconcile_limited_time_to_activity(row) -> Any:
    """限时限量购已结束但活动未预约时补推进（含 waiting_limited_time / waiting_activity）。"""
    if not row or row.status in TERMINAL_PIPELINE_STATUSES:
        return row
    if row.campaign_run_id or row.scheduled_activity_at:
        return row
    if not _listing_batches_complete_for_activity(row):
        return row

    lt_run_id = _pipeline_limited_time_run_id(row)
    if not lt_run_id:
        return row

    store = TaskRunStore()
    record = store.load(lt_run_id)
    if not record:
        return row
    run_status = _run_status_value(record.status)
    if run_status not in {RunStatus.SUCCESS, RunStatus.FAILED}:
        return row
    if run_status == RunStatus.FAILED and not _pipeline_continue_after_limited_time_failure(row):
        return row

    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        _per_batch_batch_log_context,
        is_per_batch_limited_time_continue_handled,
    )

    if is_per_batch_limited_time_continue_handled(row, lt_run_id):
        logger.info(
            "pipeline %s reconcile limited_time->activity skip: continue already handled run_id=%s ctx=%s",
            row.pipeline_id,
            lt_run_id,
            _per_batch_batch_log_context(row),
        )
        return row

    logger.warning(
        "pipeline %s reconcile limited_time->activity invoking finish run_id=%s status=%s ctx=%s",
        row.pipeline_id,
        lt_run_id,
        run_status,
        _per_batch_batch_log_context(row),
    )
    _on_limited_time_finished(
        row,
        run_id=lt_run_id,
        success=run_status == RunStatus.SUCCESS,
        result=record.result if isinstance(record.result, dict) else {},
        error=str(record.message or "").strip() if run_status == RunStatus.FAILED else "",
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    logger.warning(
        "reconciled pipeline %s limited_time -> activity run_id=%s status=%s",
        row.pipeline_id,
        lt_run_id,
        run_status,
    )
    return refreshed


def _reconcile_stuck_pipeline_row(row) -> Any:
    """子任务已失败/取消但链路仍 running 时自动对齐（例如浏览器被关后回调未触发）。"""
    if not row:
        return row

    from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
        reconcile_revived_failed_pipeline,
    )

    if str(getattr(row, "status", "") or "") == "failed":
        row = reconcile_revived_failed_pipeline(row)

    if row.status in TERMINAL_PIPELINE_STATUSES:
        return row

    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        backfill_missing_limited_time_batches,
        maybe_finalize_after_all_batches as maybe_finalize_std_agg_limited_time,
    )

    if backfill_missing_limited_time_batches(row):
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        meta = dict(refreshed.meta or {})
        batch_log = meta.get("std_per_batch_lt_agg_batch_log") or []
        total = int((meta.get("listing_throttle") or {}).get("total_batches") or 0)
        if (
            not meta.get("std_per_batch_lt_agg_finalized")
            and total > 0
            and isinstance(batch_log, list)
            and len(batch_log) >= total
            and meta.get("std_per_batch_lt_agg_pdd_ids")
        ):
            maybe_finalize_std_agg_limited_time(
                refreshed,
                run_id=str(meta.get("limited_time_run_id") or ""),
                success=True,
                result={},
                error="",
                schedule_activity_fn=_schedule_pipeline_activity_after_limited_time,
                advance_store_sequential_fn=_try_advance_store_sequential_after_listing_limited_time,
                summarize_run_message_fn=_summarize_run_message,
            )
        row = get_integrated_pipeline(row.pipeline_id) or refreshed

    from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
        maybe_flush_batch_lt_retry_activity_reschedule,
    )

    if maybe_flush_batch_lt_retry_activity_reschedule(row):
        row = get_integrated_pipeline(row.pipeline_id) or row

    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        reconcile_pipeline_waiting_activity,
    )

    row = reconcile_pipeline_waiting_activity(row)

    if row.status in TERMINAL_PIPELINE_STATUSES:
        return row

    if row.status in {"waiting_limited_time", "waiting_activity"} or (
        not row.campaign_run_id and not row.scheduled_activity_at
    ):
        reconciled = _reconcile_limited_time_to_activity(row)
        if reconciled is not row:
            row = reconciled

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
        if run_id == row.listing_run_id and run_status == RunStatus.FAILED:
            from pdd_agent.api.services.pipeline_listing_batch_continue import (
                is_listing_batch_failure_continuing,
            )

            step = str(row.current_step or "")
            if step.startswith("waiting_listing_batch_") or is_listing_batch_failure_continuing(
                row.pipeline_id
            ):
                continue
        if (
            run_id == _pipeline_limited_time_run_id(row)
            and run_status == RunStatus.FAILED
        ):
            from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
                should_absorb_per_batch_limited_time_failure,
            )
            from pdd_agent.api.services.pipeline_per_batch_limited_time import (
                _per_batch_batch_log_context,
                is_per_batch_limited_time_continue_handled,
            )

            if is_per_batch_limited_time_continue_handled(row, run_id):
                logger.info(
                    "pipeline %s reconcile stuck skip absorbed LT failure: already handled run_id=%s step=%s ctx=%s",
                    row.pipeline_id,
                    run_id,
                    row.current_step,
                    _per_batch_batch_log_context(row),
                )
                continue
            if dict(row.meta or {}).get("limited_time_finish_handled"):
                logger.info(
                    "pipeline %s reconcile stuck skip LT failure: finish already handled run_id=%s step=%s",
                    row.pipeline_id,
                    run_id,
                    row.current_step,
                )
                continue
            if should_absorb_per_batch_limited_time_failure(row, run_id=run_id):
                refreshed = get_integrated_pipeline(row.pipeline_id) or row
                logger.warning(
                    "pipeline %s reconcile stuck invoking absorbed LT failure run_id=%s error=%s ctx=%s",
                    row.pipeline_id,
                    run_id,
                    error[:200],
                    _per_batch_batch_log_context(refreshed),
                )
                _on_limited_time_finished(
                    refreshed,
                    run_id=run_id,
                    success=False,
                    result=record.result if isinstance(record.result, dict) else {},
                    error=str(record.message or "").strip() or "限时限量购设置失败",
                )
                continue
            if _pipeline_continue_after_limited_time_failure(row):
                refreshed = get_integrated_pipeline(row.pipeline_id) or row
                refreshed_meta = refreshed.meta if isinstance(refreshed.meta, dict) else {}
                if not refreshed.campaign_run_id and not refreshed.scheduled_activity_at:
                    if refreshed_meta.get("limited_time_finish_handled"):
                        logger.warning(
                            "reconcile pipeline %s limited_time failed with stale finish flag",
                            row.pipeline_id,
                        )
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
        if (
            failed_step == "traffic_failed"
            and run_status == RunStatus.FAILED
        ):
            from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
                should_absorb_traffic_failure_after_batch_lt_revive,
            )

            if should_absorb_traffic_failure_after_batch_lt_revive(row, run_id):
                logger.info(
                    "pipeline %s reconcile skip stale traffic failure after batch lt revive run_id=%s",
                    row.pipeline_id,
                    run_id,
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
    if row:
        from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
            should_absorb_limited_time_task_failure,
        )
        from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.bridge import (
            should_absorb_queue_task_failure,
        )

        if should_absorb_queue_task_failure(row, agent=agent, run_id=run_id, success=success):
            return
        if should_absorb_limited_time_task_failure(row, agent=agent, run_id=run_id, success=success):
            return
    if agent == AgentKind.LISTING.value:
        from pdd_agent.api.services.pipeline_listing_batch_continue import (
            is_listing_batch_failure_continuing,
        )

        if is_listing_batch_failure_continuing(pipeline_id):
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
        and _pipeline_limited_time_run_id(row) == str(run_id or "").strip()
    ):
        meta = dict(row.meta or {})
        if meta.get("limited_time_finish_handled"):
            return
        from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
            should_absorb_per_batch_limited_time_failure,
        )

        if should_absorb_per_batch_limited_time_failure(row, run_id=run_id):
            return
    if (
        agent == AgentKind.CAMPAIGN.value
        and _pipeline_limited_time_run_id(row) != run_id
        and _pipeline_continue_after_activity_failure(row)
    ):
        return
    if agent == AgentKind.TRAFFIC.value:
        from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
            should_absorb_traffic_failure_after_batch_lt_revive,
        )

        if should_absorb_traffic_failure_after_batch_lt_revive(row, run_id):
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
        _reconcile_stuck_pipeline_row(row)
        if row.status not in TERMINAL_PIPELINE_STATUSES
        else row
        for row in rows
    ]
    items = [pipeline_to_dict(row) for row in reconciled]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _collect_pipeline_cancel_run_ids(row) -> list[str]:
    """整合链路取消时需停止的全部子任务 run_id（含限时限量购与分批上架）。"""
    run_ids: list[str] = []
    for rid in (row.listing_run_id, row.campaign_run_id, row.traffic_run_id):
        rid = str(rid or "").strip()
        if rid:
            run_ids.append(rid)
    lt_rid = _pipeline_limited_time_run_id(row)
    if lt_rid:
        run_ids.append(lt_rid)
    pipeline_id = str(row.pipeline_id or "").strip()
    if pipeline_id:
        from pdd_agent.db.repositories import list_listing_run_ids_for_pipeline

        run_ids.extend(list_listing_run_ids_for_pipeline(pipeline_id))
    return list(dict.fromkeys(run_ids))


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

    run_ids = _collect_pipeline_cancel_run_ids(row)
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
    if refreshed:
        try:
            from pdd_agent.api.services.pipeline_store_sequential import maybe_advance_sequential_store

            maybe_advance_sequential_store(refreshed)
        except Exception:
            logger.exception("advance sequential store after cancel failed pipeline_id=%s", pipeline_id)
    return pipeline_to_dict(refreshed or row)

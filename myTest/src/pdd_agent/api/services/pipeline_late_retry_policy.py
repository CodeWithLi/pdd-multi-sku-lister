"""
整合链路 — 等活动 24h 期间补跑上架失败项（方案 A）。

主批次上架 + 限时限量购已完成、活动已预约（waiting_activity）时，允许对失败套图补跑：
  补跑上架 → 限时限量购 → 并入 activity_pdd_product_ids，仍按原 scheduled_activity_at 报活动。

不修改主链路状态机；通过独立 meta 状态 + 队列回调钩子接入。

回滚：删除 pipeline_service / task_queue / pipelines 路由内对本模块的引用即可。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.api.services.task_runner import create_campaign_run, create_listing_run
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import enqueue_task, get_integrated_pipeline, update_integrated_pipeline
from pdd_agent.domain.enums import AgentKind, RunStatus
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)

META_STATE_KEY = "pipeline_late_retry"
POLICY_META_FLAG = "pipeline_late_retry_enabled"

# 活动触发前至少保留的缓冲（上架 + 限时购预估）
DEFAULT_DEADLINE_BUFFER_MINUTES = 30

PHASE_IDLE = "idle"
PHASE_LISTING = "listing"
PHASE_LIMITED_TIME = "limited_time"
PHASE_DONE = "done"
PHASE_PARTIAL = "partial_done"
PHASE_EXPIRED = "expired"

ACTIVE_PHASES = frozenset({PHASE_LISTING, PHASE_LIMITED_TIME})


def _meta(row) -> dict[str, Any]:
    raw = getattr(row, "meta", None) if row is not None else None
    return dict(raw) if isinstance(raw, dict) else {}


def late_retry_state(row) -> dict[str, Any]:
    state = _meta(row).get(META_STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}


def is_late_retry_enabled(row) -> bool:
    state = late_retry_state(row)
    if not state:
        return False
    if POLICY_META_FLAG in state:
        return bool(state[POLICY_META_FLAG])
    return bool(state.get("enabled"))


def is_late_retry_listing_run(row, run_id: str) -> bool:
    rid = str(run_id or "").strip()
    if not rid:
        return False
    state = late_retry_state(row)
    return str(state.get("listing_run_id") or "").strip() == rid


def is_late_retry_limited_time_run(row, run_id: str) -> bool:
    rid = str(run_id or "").strip()
    if not rid:
        return False
    state = late_retry_state(row)
    return str(state.get("limited_time_run_id") or "").strip() == rid


def _activity_deadline(row) -> datetime | None:
    scheduled = getattr(row, "scheduled_activity_at", None)
    if isinstance(scheduled, datetime):
        return scheduled
    state = late_retry_state(row)
    raw = str(state.get("activity_deadline_at") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _minutes_until_deadline(row) -> float | None:
    deadline = _activity_deadline(row)
    if not deadline:
        return None
    return (deadline - datetime.now()).total_seconds() / 60.0


def _merge_unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def list_failed_selectors(row) -> list[str]:
    from pdd_agent.api.services.pipeline_service import build_listing_unit_statuses

    selectors: list[str] = []
    for item in build_listing_unit_statuses(row):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip() != "failed":
            continue
        selector = str(item.get("selector") or "").strip()
        if selector:
            selectors.append(selector)
    return list(dict.fromkeys(selectors))


def _buffer_minutes(row) -> int:
    state = late_retry_state(row)
    raw = state.get("deadline_buffer_minutes")
    if raw is not None:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    return DEFAULT_DEADLINE_BUFFER_MINUTES


def evaluate_late_retry_eligibility(row) -> dict[str, Any]:
    """返回可否补跑及原因（供 API / 前端展示）。"""
    if row is None:
        return {"eligible": False, "reason": "pipeline_not_found"}

    status = str(getattr(row, "status", "") or "")
    step = str(getattr(row, "current_step", "") or "")
    deadline = _activity_deadline(row)
    now = datetime.now()

    if status not in {"waiting_activity", "running"}:
        return {"eligible": False, "reason": "pipeline_not_waiting_activity", "status": status}
    if step != "waiting_activity":
        return {
            "eligible": False,
            "reason": "pipeline_not_in_waiting_activity_step",
            "current_step": step,
        }
    if not deadline and not getattr(row, "campaign_run_id", None):
        return {"eligible": False, "reason": "activity_not_scheduled"}

    state = late_retry_state(row)
    phase = str(state.get("phase") or PHASE_IDLE)
    if phase in ACTIVE_PHASES:
        base = {
            "eligible": False,
            "reason": "late_retry_in_progress",
            "phase": phase,
        }
        return _augment_eligibility(row, base)

    failed = list_failed_selectors(row)
    if not failed:
        return _augment_eligibility(row, {"eligible": False, "reason": "no_failed_selectors"})

    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import is_defer_policy_enabled

    if is_defer_policy_enabled(row):
        return _augment_eligibility(
            row,
            {
                "eligible": True,
                "failed_selectors": failed,
                "failed_count": len(failed),
                "activity_deadline_at": deadline.isoformat() if deadline else "",
            },
        )

    if not deadline:
        return {"eligible": False, "reason": "activity_not_scheduled"}
    if deadline <= now:
        return {
            "eligible": False,
            "reason": "activity_deadline_passed",
            "activity_deadline_at": deadline.isoformat(),
        }

    remaining = (deadline - now).total_seconds() / 60.0
    buffer_min = _buffer_minutes(row)
    if remaining < buffer_min:
        return {
            "eligible": False,
            "reason": "insufficient_time_before_activity",
            "minutes_remaining": round(remaining, 1),
            "required_buffer_minutes": buffer_min,
            "activity_deadline_at": deadline.isoformat(),
        }

    return {
        "eligible": True,
        "failed_selectors": failed,
        "failed_count": len(failed),
        "minutes_remaining": round(remaining, 1),
        "required_buffer_minutes": buffer_min,
        "activity_deadline_at": deadline.isoformat(),
    }


def _augment_eligibility(row, eligibility: dict[str, Any]) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import augment_late_retry_eligibility

    return augment_late_retry_eligibility(row, eligibility)


def build_late_retry_public_state(row) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
        build_activity_defer_public_state,
    )

    state = late_retry_state(row)
    activity_defer = build_activity_defer_public_state(row)
    if not state:
        eligibility = evaluate_late_retry_eligibility(row)
        return {
            "enabled": False,
            "phase": PHASE_IDLE,
            "eligible": bool(eligibility.get("eligible")),
            "eligibility": eligibility,
            "activity_defer": activity_defer,
        }
    deadline = _activity_deadline(row)
    scheduled = getattr(row, "scheduled_activity_at", None)
    display_deadline = scheduled if isinstance(scheduled, datetime) else deadline
    return {
        "enabled": is_late_retry_enabled(row),
        "phase": str(state.get("phase") or PHASE_IDLE),
        "outcome": str(state.get("outcome") or ""),
        "outcome_detail": str(state.get("outcome_detail") or ""),
        "selectors": list(state.get("selectors") or []),
        "succeeded_selectors": list(state.get("succeeded_selectors") or []),
        "failed_selectors": list(state.get("failed_selectors") or []),
        "expired_selectors": list(state.get("expired_selectors") or []),
        "listing_run_id": str(state.get("listing_run_id") or ""),
        "limited_time_run_id": str(state.get("limited_time_run_id") or ""),
        "activity_deadline_at": display_deadline.isoformat() if display_deadline else "",
        "minutes_remaining": (
            round((display_deadline - datetime.now()).total_seconds() / 60.0, 1)
            if isinstance(display_deadline, datetime)
            else None
        ),
        "merged_pdd_count": int(state.get("merged_pdd_count") or 0),
        "eligible": evaluate_late_retry_eligibility(row).get("eligible"),
        "eligibility": evaluate_late_retry_eligibility(row),
        "activity_defer": activity_defer,
    }


def merge_late_retry_listing_statuses(row, statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将补跑上架 run 的结果覆盖到套图状态表（仅展示，不改主链路 meta）。"""
    state = late_retry_state(row)
    run_id = str(state.get("listing_run_id") or "").strip()
    if not run_id:
        return statuses

    record = TaskRunStore().load(run_id)
    if not record:
        return statuses
    result = dict(record.result or {})
    results_by_label: dict[str, dict[str, Any]] = {}
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("listing_label") or "").strip()
        if label:
            results_by_label[label] = item

    if not results_by_label:
        return statuses

    from pdd_agent.api.services.pipeline_service import LISTING_UNIT_STATUS_LABELS

    merged: list[dict[str, Any]] = []
    for row_item in statuses:
        item = dict(row_item)
        label = str(item.get("listing_label") or "").strip()
        retry_item = results_by_label.get(label)
        if not retry_item:
            merged.append(item)
            continue
        item_status = str(retry_item.get("status") or "").strip().lower()
        product_id = str(retry_item.get("pdd_product_id") or "").strip()
        if item_status in {"success", "listed"} and (product_id or item_status == "listed"):
            item["status"] = "success"
            item["status_label"] = LISTING_UNIT_STATUS_LABELS.get("success", "success")
            item["reason_code"] = ""
        elif item_status in {"failed", "retryable"}:
            item["status"] = "failed"
            item["status_label"] = LISTING_UNIT_STATUS_LABELS.get("failed", "failed")
            item["reason_code"] = str(
                retry_item.get("reason") or retry_item.get("reason_code") or "listing_failed"
            )
        merged.append(item)
    return merged


def _save_late_retry_state(row, patch: dict[str, Any]) -> None:
    meta = _meta(row)
    current = dict(meta.get(META_STATE_KEY) or {})
    current.update(patch)
    update_integrated_pipeline(row.pipeline_id, meta_patch={META_STATE_KEY: current})


def _is_past_deadline(row) -> bool:
    deadline = _activity_deadline(row)
    return bool(deadline and deadline <= datetime.now())


def _listing_payload_base(row) -> dict[str, Any]:
    meta = _meta(row)
    settings = load_yaml_settings()
    return {
        "category_keyword": settings.listing.category_keyword,
        "platform_listing_code": "",
        "slot_alignment_test": bool(meta.get("slot_alignment_test")),
        "spec_fill_verify_test": bool(meta.get("spec_fill_verify_test")),
        "primary_style_first_test": bool(meta.get("primary_style_first_test")),
        "paren_size_as_product_type": bool(meta.get("paren_size_as_product_type")),
        "category_next_burst_demo": bool(meta.get("category_next_burst_demo", True)),
        "material_source": str(meta.get("material_source") or ""),
        "use_minio_cache_only": bool(meta.get("use_minio_cache_only")),
    }


def start_late_retry_failed(
    pipeline_id: str,
    *,
    selectors: list[str] | None = None,
    deadline_buffer_minutes: int | None = None,
) -> dict[str, Any]:
    """启动补跑：入队失败套图上架。"""
    pipeline_id = str(pipeline_id or "").strip()
    row = get_integrated_pipeline(pipeline_id)
    if not row:
        raise ValueError("pipeline_not_found")

    eligibility = evaluate_late_retry_eligibility(row)
    if deadline_buffer_minutes is not None:
        eligibility = dict(eligibility)
        buffer = max(0, int(deadline_buffer_minutes))
        remaining = eligibility.get("minutes_remaining")
        if remaining is not None and remaining < buffer:
            eligibility["eligible"] = False
            eligibility["reason"] = "insufficient_time_before_activity"
            eligibility["required_buffer_minutes"] = buffer

    if not eligibility.get("eligible"):
        reason = str(eligibility.get("reason") or "not_eligible")
        raise ValueError(reason)

    requested = list(dict.fromkeys(str(s).strip() for s in (selectors or []) if str(s).strip()))
    failed = list(eligibility.get("failed_selectors") or list_failed_selectors(row))
    if requested:
        failed_set = set(failed)
        target = [s for s in requested if s in failed_set]
        if not target:
            raise ValueError("no_matching_failed_selectors")
    else:
        target = failed

    deadline = _activity_deadline(row)
    if not deadline:
        raise ValueError("activity_not_scheduled")

    account_id = str(row.account_id or "").strip()
    if not account_id:
        raise ValueError("account_id_missing")

    payload_base = _listing_payload_base(row)
    run_id = create_listing_run(account_id)
    TaskRunStore().update_status(run_id, RunStatus.PENDING, "pipeline late retry listing queued")

    buffer = (
        max(0, int(deadline_buffer_minutes))
        if deadline_buffer_minutes is not None
        else _buffer_minutes(row)
    )
    state_patch = {
        POLICY_META_FLAG: True,
        "enabled": True,
        "phase": PHASE_LISTING,
        "selectors": target,
        "pending_selectors": target,
        "succeeded_selectors": [],
        "failed_selectors": [],
        "expired_selectors": [],
        "listing_run_id": run_id,
        "limited_time_run_id": "",
        "activity_deadline_at": deadline.isoformat(),
        "deadline_buffer_minutes": buffer,
        "started_at": datetime.now().isoformat(),
        "outcome": "",
        "outcome_detail": "",
        "merged_pdd_count": 0,
    }
    _save_late_retry_state(row, state_patch)

    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
        is_defer_policy_enabled,
    )

    if is_defer_policy_enabled(row):
        scheduled = getattr(row, "scheduled_activity_at", None)
        update_integrated_pipeline(
            pipeline_id,
            meta_patch={
                "pipeline_late_retry_activity_defer": {
                    "original_activity_at": scheduled.isoformat() if isinstance(scheduled, datetime) else "",
                    "awaiting_reschedule": False,
                }
            },
        )

    enqueue_task(
        agent=AgentKind.LISTING.value,
        run_id=run_id,
        account_id=account_id,
        payload={
            "product_codes": target,
            "dry_run": False,
            "category_keyword": str(payload_base.get("category_keyword") or "玩偶"),
            "platform_listing_code": "",
            "pipeline_id": pipeline_id,
            "pipeline_late_retry": True,
            "slot_alignment_test": bool(payload_base.get("slot_alignment_test")),
            "spec_fill_verify_test": bool(payload_base.get("spec_fill_verify_test")),
            "primary_style_first_test": bool(payload_base.get("primary_style_first_test")),
            "paren_size_as_product_type": bool(payload_base.get("paren_size_as_product_type")),
            "category_next_burst_demo": bool(payload_base.get("category_next_burst_demo", True)),
            "material_source": str(payload_base.get("material_source") or ""),
            "use_minio_cache_only": bool(payload_base.get("use_minio_cache_only")),
        },
        scheduled_at=datetime.now(),
    )

    logger.info(
        "pipeline %s late retry started run_id=%s selectors=%s deadline=%s",
        pipeline_id,
        run_id,
        len(target),
        deadline,
    )
    refreshed = get_integrated_pipeline(pipeline_id) or row
    return {
        "pipeline_id": pipeline_id,
        "listing_run_id": run_id,
        "selector_count": len(target),
        "selectors": target,
        "activity_deadline_at": deadline.isoformat(),
        "late_retry": build_late_retry_public_state(refreshed),
    }


def _classify_listing_outcome(result: dict[str, Any], selectors: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    from pdd_agent.api.services.pipeline_service import _extract_listing_products, _selector_to_listing_label

    succeeded: list[str] = []
    failed: list[str] = []
    pdd_ids: list[str] = []
    mapping_ids: list[str] = []

    results_by_label: dict[str, dict[str, Any]] = {}
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("listing_label") or "").strip()
        if label:
            results_by_label[label] = item

    for selector in selectors:
        label = _selector_to_listing_label(selector)
        item = results_by_label.get(label)
        if not item:
            failed.append(selector)
            continue
        status = str(item.get("status") or "").strip().lower()
        product_id = str(item.get("pdd_product_id") or "").strip()
        if status in {"success", "listed"} and (product_id or status == "listed"):
            succeeded.append(selector)
        else:
            failed.append(selector)

    pdd_ids, mapping_ids = _extract_listing_products(result)
    return succeeded, failed, pdd_ids, mapping_ids


def _mark_expired(row, *, detail: str, selectors: list[str] | None = None) -> None:
    state = late_retry_state(row)
    expired = list(state.get("expired_selectors") or [])
    if selectors:
        expired = _merge_unique([*expired, *selectors])
    _save_late_retry_state(
        row,
        {
            "phase": PHASE_EXPIRED,
            "outcome": "deadline_passed",
            "outcome_detail": detail,
            "expired_selectors": expired,
            "pending_selectors": [],
        },
    )
    logger.warning("pipeline %s late retry expired: %s", row.pipeline_id, detail)


def _enqueue_late_retry_limited_time(row, *, pdd_ids: list[str], mapping_ids: list[str]) -> str:
    limited_time_run_id = create_campaign_run(str(row.account_id or ""))
    enqueue_task(
        agent=AgentKind.CAMPAIGN.value,
        run_id=limited_time_run_id,
        account_id=str(row.account_id or ""),
        payload={
            "pipeline_id": row.pipeline_id,
            "campaign_type": "limited_time_setup",
            "pdd_product_ids": list(pdd_ids),
            "published_mapping_ids": list(mapping_ids),
            "pipeline_late_retry": True,
        },
        scheduled_at=datetime.now() + timedelta(seconds=5),
    )
    _save_late_retry_state(
        row,
        {
            "phase": PHASE_LIMITED_TIME,
            "limited_time_run_id": limited_time_run_id,
        },
    )
    logger.info(
        "pipeline %s late retry limited time queued run_id=%s pdd_ids=%s",
        row.pipeline_id,
        limited_time_run_id,
        pdd_ids,
    )
    return limited_time_run_id


def _merge_limited_time_success_into_activity_pool(row, *, run_id: str, result: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        META_ACTIVITY_PDD_IDS_KEY,
        META_LT_SUCCESS_MAPPING_IDS_KEY,
        META_LT_SUCCESS_PDD_IDS_KEY,
        build_limited_time_success_meta_patch,
        extract_limited_time_success_products,
    )
    from pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy import (
        ACCUMULATED_MAPPING_IDS_KEY,
        ACCUMULATED_PDD_IDS_KEY,
    )

    meta = _meta(row)
    extract = extract_limited_time_success_products(
        result,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=[],
        fallback_mapping_ids=[],
    )

    existing_pdd = _merge_unique(
        list(meta.get(META_ACTIVITY_PDD_IDS_KEY) or [])
        + list(meta.get(META_LT_SUCCESS_PDD_IDS_KEY) or [])
        + list(meta.get(ACCUMULATED_PDD_IDS_KEY) or [])
        + list(row.pdd_product_ids or [])
    )
    existing_map = _merge_unique(
        list(meta.get(META_LT_SUCCESS_MAPPING_IDS_KEY) or [])
        + list(meta.get(ACCUMULATED_MAPPING_IDS_KEY) or [])
        + list(row.mapping_ids or [])
    )

    merged_pdd = _merge_unique([*existing_pdd, *extract.pdd_product_ids])
    merged_map = _merge_unique([*existing_map, *extract.mapping_ids])

    from pdd_agent.api.services.pipeline_activity_limited_time_success import LimitedTimeSuccessProducts

    patch = build_limited_time_success_meta_patch(
        LimitedTimeSuccessProducts(
            pdd_product_ids=merged_pdd,
            mapping_ids=merged_map,
            source="late_retry_limited_time_success",
            detail=(
                f"补跑限时成功 {len(extract.pdd_product_ids)} 个，"
                f"活动池合计 {len(merged_pdd)} 个"
            ),
        )
    )
    patch[ACCUMULATED_PDD_IDS_KEY] = merged_pdd
    patch[ACCUMULATED_MAPPING_IDS_KEY] = merged_map
    patch["late_retry_limited_time_run_id"] = str(run_id or "").strip()
    patch["late_retry_limited_time_detail"] = extract.detail

    update_integrated_pipeline(
        row.pipeline_id,
        pdd_product_ids=merged_pdd,
        mapping_ids=merged_map,
        meta_patch=patch,
    )
    return merged_pdd, merged_map


def maybe_handle_late_retry_listing_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any],
    error: str,
) -> bool:
    if not is_late_retry_listing_run(row, run_id):
        return False

    result = result if isinstance(result, dict) else {}
    state = late_retry_state(row)
    selectors = list(state.get("selectors") or state.get("pending_selectors") or [])

    succeeded, failed, pdd_ids, mapping_ids = _classify_listing_outcome(result, selectors)
    batch_resume = result.get("batch_resume") if isinstance(result.get("batch_resume"), dict) else {}
    skipped_run = bool(batch_resume.get("skipped_run"))

    if not pdd_ids:
        if skipped_run:
            detail = "补跑未实际上架（被分批续跑误判为已完成），请重新点击补跑"
            outcome = "listing_skipped_batch_resume"
        elif not success and not succeeded:
            detail = error or "补跑上架失败"
            outcome = "listing_failed"
        else:
            detail = "补跑上架无成功商品 ID"
            outcome = "listing_no_pdd_ids"
        _save_late_retry_state(
            row,
            {
                "phase": PHASE_IDLE,
                "outcome": outcome,
                "outcome_detail": detail,
                "succeeded_selectors": succeeded,
                "failed_selectors": failed,
                "pending_selectors": [],
            },
        )
        return True

    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
        record_late_retry_listing_finished_at,
    )

    record_late_retry_listing_finished_at(row)

    _save_late_retry_state(
        row,
        {
            "succeeded_selectors": succeeded,
            "failed_selectors": failed,
            "pending_selectors": [],
        },
    )
    lt_run_id = _enqueue_late_retry_limited_time(row, pdd_ids=pdd_ids, mapping_ids=mapping_ids)
    if not lt_run_id:
        return True

    return True


def maybe_handle_late_retry_limited_time_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any],
    error: str,
) -> bool:
    if not is_late_retry_limited_time_run(row, run_id):
        return False

    result = result if isinstance(result, dict) else {}
    state = late_retry_state(row)
    selectors = list(state.get("selectors") or [])

    merged_pdd, merged_map = _merge_limited_time_success_into_activity_pool(
        row,
        run_id=run_id,
        result=result,
    )

    failed_selectors = list(state.get("failed_selectors") or [])
    phase = PHASE_DONE if not failed_selectors else PHASE_PARTIAL
    outcome = "limited_time_merged" if merged_pdd else "limited_time_no_success"
    detail = ""
    if merged_pdd:
        detail = f"已并入活动池 {len(merged_pdd)} 个商品"
    else:
        detail = error or "补跑限时限量购无成功商品"

    if not success and not merged_pdd:
        phase = PHASE_PARTIAL
        outcome = "limited_time_failed"
        detail = error or "补跑限时限量购失败"

    _save_late_retry_state(
        row,
        {
            "phase": phase,
            "outcome": outcome,
            "outcome_detail": detail,
            "merged_pdd_count": len(merged_pdd),
            "limited_time_run_id": str(run_id or "").strip(),
        },
    )
    logger.info(
        "pipeline %s late retry limited time done success=%s merged=%s",
        row.pipeline_id,
        success,
        len(merged_pdd),
    )
    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
        maybe_reschedule_activity_after_late_retry_batch,
    )

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    maybe_reschedule_activity_after_late_retry_batch(refreshed)
    return True


def dispatch_late_retry_queue_task_finished(
    row,
    *,
    agent: str,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    """队列任务结束时优先处理补跑子流程，避免触发主链路失败逻辑。"""
    if row is None:
        return False
    result = result if isinstance(result, dict) else {}
    agent_name = str(agent or "").strip()

    if agent_name == AgentKind.LISTING.value:
        return maybe_handle_late_retry_listing_finished(
            row,
            run_id=run_id,
            success=success,
            result=result,
            error=error,
        )
    if agent_name == AgentKind.CAMPAIGN.value and is_late_retry_limited_time_run(row, run_id):
        return maybe_handle_late_retry_limited_time_finished(
            row,
            run_id=run_id,
            success=success,
            result=result,
            error=error,
        )
    return False


def finalize_late_retry_before_activity_execution(pipeline_id: str) -> None:
    """活动执行前：延期策略下不再将补跑标过期（由 defer 模块在活动到期时推迟）。"""
    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
        is_defer_policy_enabled,
    )

    row = get_integrated_pipeline(str(pipeline_id or "").strip())
    if not row:
        return

    if is_defer_policy_enabled(row):
        return
    state = late_retry_state(row)
    phase = str(state.get("phase") or PHASE_IDLE)
    if phase not in ACTIVE_PHASES:
        return
    _mark_expired(
        row,
        detail="活动任务已开始执行，进行中的补跑未能赶上当次预约",
        selectors=list(state.get("pending_selectors") or state.get("selectors") or []),
    )


def resolve_campaign_pdd_ids_at_execution(
    *,
    pipeline_id: str,
    payload_pdd_ids: list[str],
) -> list[str]:
    """
    活动执行时读取 pipeline 上最新的活动商品池（含补跑并入），而非入队时写死的 payload。
    """
    pipeline_id = str(pipeline_id or "").strip()
    if pipeline_id:
        finalize_late_retry_before_activity_execution(pipeline_id)
        row = get_integrated_pipeline(pipeline_id)
        if row:
            from pdd_agent.api.services.pipeline_activity_limited_time_success import (
                resolve_activity_product_ids_for_row,
            )

            resolved, _mapping = resolve_activity_product_ids_for_row(row)
            if resolved:
                logger.info(
                    "pipeline %s campaign execution resolved pdd_ids=%s (payload had %s)",
                    pipeline_id,
                    len(resolved),
                    len(payload_pdd_ids or []),
                )
                return resolved
    return list(payload_pdd_ids or [])

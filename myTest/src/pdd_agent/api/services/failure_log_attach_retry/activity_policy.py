"""失败日志挂回原链路 — 活动顺延 / 改期（对齐分批限时重跑）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.api.services.failure_log_attach_retry.constants import (
    ACTIVE_PHASES,
    DEFER_POLL_MINUTES,
    META_DEFER_KEY,
    META_STATE_KEY,
)
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    get_integrated_pipeline,
    get_queue_task_by_run_id,
    requeue_running_task,
    update_integrated_pipeline,
    update_queued_task_schedule,
)

logger = get_logger(__name__)


def _meta(row) -> dict[str, Any]:
    raw = getattr(row, "meta", None) if row is not None else None
    return dict(raw) if isinstance(raw, dict) else {}


def _defer_state(row) -> dict[str, Any]:
    state = _meta(row).get(META_DEFER_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _save_defer(row, patch: dict[str, Any]) -> None:
    current = _defer_state(row)
    current.update(patch)
    update_integrated_pipeline(row.pipeline_id, meta_patch={META_DEFER_KEY: current})


def attach_retry_state(row) -> dict[str, Any]:
    state = _meta(row).get(META_STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}


def is_attach_retry_in_progress(row) -> bool:
    if row is None:
        return False
    phase = str(attach_retry_state(row).get("phase") or "")
    return phase in ACTIVE_PHASES


def should_defer_activity_for_attach_retry(row) -> tuple[bool, str]:
    if row is None:
        return False, ""
    if is_attach_retry_in_progress(row):
        return True, "失败日志挂回原链路重跑进行中，活动等待结束后再执行"
    return False, ""


def maybe_defer_activity_task_execution(row, *, task_id: str, run_id: str) -> bool:
    should, reason = should_defer_activity_for_attach_retry(row)
    if not should:
        return False
    poll_at = datetime.now() + timedelta(minutes=DEFER_POLL_MINUTES)
    ok = requeue_running_task(task_id, scheduled_at=poll_at, error=reason)
    if not ok:
        logger.warning(
            "pipeline %s attach retry activity defer failed task_id=%s run_id=%s",
            getattr(row, "pipeline_id", ""),
            task_id,
            run_id,
        )
        return False
    defer_count = int(_defer_state(row).get("defer_count") or 0) + 1
    _save_defer(
        row,
        {
            "last_deferred_at": datetime.now().isoformat(),
            "last_defer_reason": reason,
            "defer_count": defer_count,
        },
    )
    logger.info(
        "pipeline %s activity deferred (attach retry) until %s run_id=%s",
        row.pipeline_id,
        poll_at,
        run_id,
    )
    return True


def record_attach_retry_success_finished_at(row, *, finished_at: datetime | None = None) -> None:
    ts = finished_at or datetime.now()
    original = str(_defer_state(row).get("original_activity_at") or "").strip()
    if not original:
        scheduled = getattr(row, "scheduled_activity_at", None)
        if isinstance(scheduled, datetime):
            original = scheduled.isoformat()
    _save_defer(
        row,
        {
            "limited_time_finished_at": ts.isoformat(),
            "original_activity_at": original,
            "awaiting_reschedule": True,
        },
    )


def build_activity_revive_meta_patch(*, reason: str = "") -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
        build_activity_revive_meta_patch as _build,
    )

    patch = _build(reason=reason)
    patch["failure_log_attach_retry_revived_activity"] = True
    return patch


def maybe_finalize_activity_after_attach_retry(row) -> bool:
    """挂回原链路限时成功后：按最后成功时刻 + delay 改期/复活活动。"""
    if row is None:
        return False
    if is_attach_retry_in_progress(row):
        return False

    defer_state = _defer_state(row)
    if not defer_state.get("awaiting_reschedule"):
        return False

    anchor_raw = str(defer_state.get("limited_time_finished_at") or "").strip()
    if not anchor_raw:
        return False
    try:
        anchor = datetime.fromisoformat(anchor_raw)
    except ValueError:
        return False

    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        resolve_activity_product_ids_for_row,
    )
    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
        resolve_activity_scheduled_at_from_anchor,
    )

    new_at = resolve_activity_scheduled_at_from_anchor(
        anchor=anchor,
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )
    pdd_ids, mapping_ids = resolve_activity_product_ids_for_row(row)
    if not pdd_ids:
        logger.warning("pipeline %s attach retry finalize skipped: empty activity pool", row.pipeline_id)
        return False

    campaign_run_id = str(getattr(row, "campaign_run_id", "") or "").strip()
    reason = (
        f"失败日志挂回原链路限时已完成，活动改按最后成功时刻 {anchor:%Y-%m-%d %H:%M} 起 "
        f"{float(row.activity_delay_hours or 24.0):g}h 后执行"
    )

    if campaign_run_id:
        task = get_queue_task_by_run_id(campaign_run_id)
        if task and str(task.status or "") == "queued":
            if not update_queued_task_schedule(task.task_id, scheduled_at=new_at, error=""):
                return False
        elif task and str(task.status or "") == "running":
            requeue_running_task(
                task.task_id,
                scheduled_at=new_at,
                error="失败日志挂回原链路结束后重新预约活动",
            )
        else:
            campaign_run_id = ""

    if not campaign_run_id:
        from pdd_agent.api.services.pipeline_service import _schedule_pipeline_campaign

        revive_patch = build_activity_revive_meta_patch(reason=reason)
        revive_patch["limited_time_outcome"] = "partial_success"
        _schedule_pipeline_campaign(
            row,
            activity_index=0,
            scheduled_at=new_at,
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
            meta_patch=revive_patch,
        )
        update_integrated_pipeline(row.pipeline_id, traffic_run_id="", error="")
    else:
        update_integrated_pipeline(
            row.pipeline_id,
            status="waiting_activity",
            current_step="waiting_activity",
            scheduled_activity_at=new_at,
            pdd_product_ids=pdd_ids,
            mapping_ids=mapping_ids,
            traffic_run_id="",
            error="",
            meta_patch=build_activity_revive_meta_patch(reason=reason),
        )

    _save_defer(
        row,
        {
            "rescheduled": True,
            "reschedule_reason": reason,
            "rescheduled_at": datetime.now().isoformat(),
            "awaiting_reschedule": False,
            "scheduled_activity_at": new_at.isoformat(),
        },
    )
    logger.info(
        "pipeline %s activity finalized after attach retry anchor=%s new_at=%s pdd_count=%s",
        row.pipeline_id,
        anchor,
        new_at,
        len(pdd_ids),
    )
    return True


def build_attach_retry_activity_public_state(row) -> dict[str, Any]:
    state = _defer_state(row)
    scheduled = getattr(row, "scheduled_activity_at", None)
    return {
        "awaiting_reschedule": bool(state.get("awaiting_reschedule")),
        "rescheduled": bool(state.get("rescheduled")),
        "reschedule_reason": str(state.get("reschedule_reason") or ""),
        "defer_count": int(state.get("defer_count") or 0),
        "scheduled_activity_at": scheduled.isoformat() if isinstance(scheduled, datetime) else "",
        "limited_time_finished_at": str(state.get("limited_time_finished_at") or ""),
    }

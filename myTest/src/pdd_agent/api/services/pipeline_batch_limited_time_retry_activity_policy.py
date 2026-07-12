"""
分批限时限量购重跑 — 活动顺延策略。

规则：
  1. 重跑进行中且活动到期 → 推迟活动任务；
  2. 全部排队批次重跑结束且至少有一次成功 → 以「最后一次成功批次的限时完成时刻」+ delay 预约/改期活动；
  3. 重跑全失败 → 不改活动预约。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    get_integrated_pipeline,
    get_queue_task_by_run_id,
    requeue_running_task,
    update_integrated_pipeline,
    update_queued_task_schedule,
)

logger = get_logger(__name__)

DEFER_META_KEY = "pipeline_batch_lt_retry_activity_defer"
POLICY_META_FLAG = "pipeline_batch_lt_retry_activity_defer_enabled"
DEFER_POLL_MINUTES = 10


def is_defer_policy_enabled(row) -> bool:
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    if POLICY_META_FLAG in meta:
        return bool(meta[POLICY_META_FLAG])
    if DEFER_META_KEY in meta and isinstance(meta.get(DEFER_META_KEY), dict):
        if POLICY_META_FLAG in meta[DEFER_META_KEY]:
            return bool(meta[DEFER_META_KEY][POLICY_META_FLAG])
    return True


def _defer_meta(row) -> dict[str, Any]:
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    state = meta.get(DEFER_META_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _save_defer_meta(row, patch: dict[str, Any]) -> None:
    current = _defer_meta(row)
    current.update(patch)
    update_integrated_pipeline(row.pipeline_id, meta_patch={DEFER_META_KEY: current})


def build_batch_lt_retry_activity_defer_public_state(row) -> dict[str, Any]:
    state = _defer_meta(row)
    if not state:
        return {"enabled": is_defer_policy_enabled(row)}
    scheduled = getattr(row, "scheduled_activity_at", None)
    return {
        "enabled": is_defer_policy_enabled(row),
        "awaiting_reschedule": bool(state.get("awaiting_reschedule")),
        "rescheduled": bool(state.get("rescheduled")),
        "reschedule_reason": str(state.get("reschedule_reason") or ""),
        "original_activity_at": str(state.get("original_activity_at") or ""),
        "limited_time_finished_at": str(state.get("limited_time_finished_at") or ""),
        "last_deferred_at": str(state.get("last_deferred_at") or ""),
        "defer_count": int(state.get("defer_count") or 0),
        "scheduled_activity_at": scheduled.isoformat() if isinstance(scheduled, datetime) else "",
    }


def is_batch_lt_retry_in_progress(row) -> bool:
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        ACTIVE_PHASES,
        batch_lt_retry_state,
    )

    if not row:
        return False
    state = batch_lt_retry_state(row)
    return str(state.get("phase") or "") in ACTIVE_PHASES


def should_defer_activity_for_batch_lt_retry(row) -> tuple[bool, str]:
    if row is None or not is_defer_policy_enabled(row):
        return False, ""
    if str(getattr(row, "current_step", "") or "") not in {
        "waiting_activity",
        "batch_limited_time_retry",
    }:
        if str(getattr(row, "status", "") or "") != "running":
            return False, ""
    if is_batch_lt_retry_in_progress(row):
        return True, "分批限时重跑进行中，活动等待重跑结束后再执行"
    return False, ""


def maybe_defer_activity_task_execution(row, *, task_id: str, run_id: str) -> bool:
    if row is None:
        return False
    should, reason = should_defer_activity_for_batch_lt_retry(row)
    if not should:
        return False

    poll_at = datetime.now() + timedelta(minutes=DEFER_POLL_MINUTES)
    ok = requeue_running_task(task_id, scheduled_at=poll_at, error=reason)
    if not ok:
        logger.warning(
            "pipeline %s batch lt retry activity defer failed task_id=%s run_id=%s",
            row.pipeline_id,
            task_id,
            run_id,
        )
        return False

    defer_count = int(_defer_meta(row).get("defer_count") or 0) + 1
    _save_defer_meta(
        row,
        {
            "last_deferred_at": datetime.now().isoformat(),
            "last_defer_reason": reason,
            "defer_count": defer_count,
        },
    )
    logger.info(
        "pipeline %s activity deferred (batch lt retry) until %s run_id=%s",
        row.pipeline_id,
        poll_at,
        run_id,
    )
    return True


def record_batch_lt_retry_success_finished_at(row, *, finished_at: datetime | None = None) -> None:
    """本批重跑有成功商品时更新锚点（多批重跑取最后一次成功时刻）。"""
    if row is None or not is_defer_policy_enabled(row):
        return
    ts = finished_at or datetime.now()
    original = str(_defer_meta(row).get("original_activity_at") or "").strip()
    if not original:
        scheduled = getattr(row, "scheduled_activity_at", None)
        if isinstance(scheduled, datetime):
            original = scheduled.isoformat()
    _save_defer_meta(
        row,
        {
            "limited_time_finished_at": ts.isoformat(),
            "original_activity_at": original,
            "awaiting_reschedule": True,
        },
    )


def build_activity_revive_meta_patch(*, reason: str = "") -> dict[str, Any]:
    """分批限时重跑后复活活动：清除此前跳过/失败的活动与推广展示状态。"""
    patch: dict[str, Any] = {
        "batch_lt_retry_revived_activity": True,
        "campaign_outcome": "",
        "campaign_skip_reason": "",
        "campaign_results": [],
        "traffic_skip_reason": "",
        "traffic_finish_handled": False,
        "listing_limited_time_phase_completed": True,
    }
    if reason:
        patch["batch_lt_retry_revive_reason"] = reason
    return patch


def should_absorb_traffic_failure_after_batch_lt_revive(row, run_id: str) -> bool:
    """
    分批限时重跑已改期活动后，忽略改期前遗留的推广失败回调，避免链路再次 failed。
    """
    if row is None:
        return False
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    if not meta.get("batch_lt_retry_revived_activity"):
        return False
    defer_state = _defer_meta(row)
    if not defer_state.get("rescheduled") and not getattr(row, "scheduled_activity_at", None):
        return False
    rid = str(run_id or "").strip()
    if not rid:
        return False
    if rid != str(getattr(row, "traffic_run_id", "") or "").strip():
        return False
    step = str(getattr(row, "current_step", "") or "")
    status = str(getattr(row, "status", "") or "")
    return status in {"failed", "running", "waiting_activity"} or step in {
        "traffic_failed",
        "waiting_activity",
        "campaign_queued",
    }


def reconcile_revived_failed_pipeline(row):
    """
    failed 但分批限时重跑已成功改期活动时，恢复为 waiting_activity 并清除遗留推广 run。
    """
    if row is None or str(getattr(row, "status", "") or "") != "failed":
        return row
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    if not meta.get("batch_lt_retry_revived_activity"):
        return row
    defer_state = _defer_meta(row)
    if not defer_state.get("rescheduled") and not getattr(row, "scheduled_activity_at", None):
        return row
    step = str(getattr(row, "current_step", "") or "")
    if step not in {
        "traffic_failed",
        "activity_failed",
        "limited_time_failed",
        "failed",
        "limited_time_failed_continue",
    }:
        return row
    reason = str(defer_state.get("reschedule_reason") or meta.get("batch_lt_retry_revive_reason") or "")
    update_integrated_pipeline(
        row.pipeline_id,
        status="waiting_activity",
        current_step="waiting_activity",
        error="",
        traffic_run_id="",
        meta_patch=build_activity_revive_meta_patch(reason=reason),
    )
    logger.info(
        "pipeline %s reconciled revived failed -> waiting_activity step_was=%s",
        row.pipeline_id,
        step,
    )
    return get_integrated_pipeline(row.pipeline_id) or row


def maybe_finalize_activity_after_batch_lt_retry(row) -> bool:
    """
    全部分批限时重跑队列结束后：若至少有一批成功，则按最后成功时刻 + delay 预约/改期活动。
    仅当首轮限时阶段已全部结束（或已在等活动）时才真正改期。
    """
    if row is None or not is_defer_policy_enabled(row):
        return False
    if is_batch_lt_retry_in_progress(row):
        return False

    from pdd_agent.api.services.pipeline_batch_limited_time_retry_eligibility import (
        is_pipeline_initial_limited_time_phase_complete,
    )

    if not is_pipeline_initial_limited_time_phase_complete(row):
        logger.info(
            "pipeline %s batch lt retry success recorded; activity reschedule deferred until initial LT phase completes",
            row.pipeline_id,
        )
        return False

    defer_state = _defer_meta(row)
    if not defer_state.get("awaiting_reschedule"):
        return False

    anchor_raw = str(defer_state.get("limited_time_finished_at") or "").strip()
    if not anchor_raw:
        return False
    try:
        anchor = datetime.fromisoformat(anchor_raw)
    except ValueError:
        return False

    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
        resolve_activity_scheduled_at_from_anchor,
    )
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        resolve_activity_product_ids_for_row,
    )

    new_at = resolve_activity_scheduled_at_from_anchor(
        anchor=anchor,
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )
    pdd_ids, mapping_ids = resolve_activity_product_ids_for_row(row)
    if not pdd_ids:
        logger.warning("pipeline %s batch lt retry finalize skipped: empty activity pool", row.pipeline_id)
        return False

    campaign_run_id = str(getattr(row, "campaign_run_id", "") or "").strip()
    reason = (
        f"分批限时重跑已完成，活动改按最后成功批次限时完成时间 {anchor:%Y-%m-%d %H:%M} 起 "
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
                error="分批限时重跑结束后重新预约活动",
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
        update_integrated_pipeline(
            row.pipeline_id,
            traffic_run_id="",
            error="",
        )
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

    _save_defer_meta(
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
        "pipeline %s activity finalized after batch lt retry anchor=%s new_at=%s pdd_count=%s",
        row.pipeline_id,
        anchor,
        new_at,
        len(pdd_ids),
    )
    return True

"""
补跑期间活动延期策略（方案 A+）。

规则：
  1. 活动到期时若补跑仍在进行（上架/限时购）→ 不执行活动，短间隔轮询推迟；
  2. 本批补跑全部结束后 → 以「最后一次补跑上架完成时刻」+ activity_delay_hours 重新预约活动；
  3. 补跑成功后限时购仍执行，并在活动执行前合并进 activity 池。

回滚：删除 task_queue / pipeline_late_retry_policy 内对本模块的引用即可。
"""

from __future__ import annotations

import random
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
from pdd_agent.db.session import is_database_available

logger = get_logger(__name__)

DEFER_META_KEY = "pipeline_late_retry_activity_defer"
POLICY_META_FLAG = "pipeline_late_retry_activity_defer_enabled"

# 补跑进行中时，活动任务推迟后多久再检查
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


def resolve_activity_scheduled_at_from_anchor(
    *,
    anchor: datetime,
    demo_mode: bool,
    activity_delay_hours: float,
    jitter_max_seconds: int | None = None,
) -> datetime:
    from pdd_agent.api.services.pipeline_service import (
        _activity_jitter_max_seconds,
        _resolve_activity_delay,
    )

    base = anchor + _resolve_activity_delay(
        demo_mode=bool(demo_mode),
        activity_delay_hours=float(activity_delay_hours or 24.0),
    )
    jitter_cap = (
        jitter_max_seconds
        if jitter_max_seconds is not None
        else _activity_jitter_max_seconds(demo_mode=bool(demo_mode))
    )
    if jitter_cap > 0:
        base += timedelta(seconds=random.randint(0, jitter_cap))
    return base


def build_activity_defer_public_state(row) -> dict[str, Any]:
    state = _defer_meta(row)
    if not state:
        return {"enabled": is_defer_policy_enabled(row)}
    scheduled = getattr(row, "scheduled_activity_at", None)
    return {
        "enabled": is_defer_policy_enabled(row),
        "rescheduled": bool(state.get("rescheduled")),
        "reschedule_reason": str(state.get("reschedule_reason") or ""),
        "original_activity_at": str(state.get("original_activity_at") or ""),
        "listing_finished_at": str(state.get("listing_finished_at") or ""),
        "last_deferred_at": str(state.get("last_deferred_at") or ""),
        "defer_count": int(state.get("defer_count") or 0),
        "scheduled_activity_at": scheduled.isoformat() if isinstance(scheduled, datetime) else "",
    }


def is_late_retry_batch_in_progress(row) -> bool:
    from pdd_agent.api.services.pipeline_late_retry_policy import ACTIVE_PHASES, late_retry_state

    if not is_defer_policy_enabled(row):
        return False
    state = late_retry_state(row)
    phase = str(state.get("phase") or "")
    return phase in ACTIVE_PHASES


def should_defer_activity_for_pipeline(row) -> tuple[bool, str]:
    if row is None or not is_defer_policy_enabled(row):
        return False, ""
    if str(getattr(row, "current_step", "") or "") != "waiting_activity":
        return False, ""
    if is_late_retry_batch_in_progress(row):
        return True, "补跑进行中，活动等待补跑结束后再执行"
    return False, ""


def maybe_defer_activity_task_execution(row, *, task_id: str, run_id: str) -> bool:
    """
    活动队列任务即将执行：若补跑未结束则推迟并返回 True（调用方不应继续执行/完成该任务）。
    """
    if not is_database_available() or row is None:
        return False
    should, reason = should_defer_activity_for_pipeline(row)
    if not should:
        return False

    poll_at = datetime.now() + timedelta(minutes=DEFER_POLL_MINUTES)
    ok = requeue_running_task(
        task_id,
        scheduled_at=poll_at,
        error=reason,
    )
    if not ok:
        logger.warning(
            "pipeline %s activity defer requeue failed task_id=%s run_id=%s",
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
        "pipeline %s activity deferred (late retry in progress) until %s run_id=%s",
        row.pipeline_id,
        poll_at,
        run_id,
    )
    return True


def record_late_retry_listing_finished_at(row, *, finished_at: datetime | None = None) -> None:
    """补跑上架 run 结束时记录锚点时间（用于后续 +24h 重算活动）。"""
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
            "listing_finished_at": ts.isoformat(),
            "original_activity_at": original,
            "awaiting_reschedule": True,
        },
    )


def maybe_reschedule_activity_after_late_retry_batch(row) -> bool:
    """
    本批补跑全部结束（上架 + 限时购）后：以最后一次补跑上架完成时刻 + delay 重新预约活动。
    """
    if row is None or not is_defer_policy_enabled(row):
        return False
    if is_late_retry_batch_in_progress(row):
        return False

    defer_state = _defer_meta(row)
    if not defer_state.get("awaiting_reschedule"):
        return False

    anchor_raw = str(defer_state.get("listing_finished_at") or "").strip()
    if not anchor_raw:
        return False
    try:
        anchor = datetime.fromisoformat(anchor_raw)
    except ValueError:
        return False

    new_at = resolve_activity_scheduled_at_from_anchor(
        anchor=anchor,
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )

    campaign_run_id = str(getattr(row, "campaign_run_id", "") or "").strip()
    if not campaign_run_id:
        logger.warning("pipeline %s late retry batch done but no campaign_run_id", row.pipeline_id)
        return False

    task = get_queue_task_by_run_id(campaign_run_id)
    if task and str(task.status or "") == "queued":
        if not update_queued_task_schedule(task.task_id, scheduled_at=new_at, error=""):
            logger.warning(
                "pipeline %s reschedule activity queue update failed task_id=%s",
                row.pipeline_id,
                task.task_id,
            )
            return False
    elif task and str(task.status or "") == "running":
        # 应由 defer 拦截；兜底再推迟
        requeue_running_task(
            task.task_id,
            scheduled_at=new_at,
            error="补跑结束后重新预约活动",
        )
    else:
        logger.warning(
            "pipeline %s reschedule activity skipped: queue task status=%s run_id=%s",
            row.pipeline_id,
            getattr(task, "status", None),
            campaign_run_id,
        )
        return False

    reason = (
        f"补跑已全部完成，活动改按最后补跑上架时间 {anchor:%Y-%m-%d %H:%M} 起 "
        f"{float(row.activity_delay_hours or 24.0):g}h 后执行"
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
    update_integrated_pipeline(
        row.pipeline_id,
        status="waiting_activity",
        current_step="waiting_activity",
        scheduled_activity_at=new_at,
        error="",
        meta_patch={
            DEFER_META_KEY: {
                **_defer_meta(row),
                "rescheduled": True,
                "reschedule_reason": reason,
                "rescheduled_at": datetime.now().isoformat(),
                "awaiting_reschedule": False,
                "scheduled_activity_at": new_at.isoformat(),
            }
        },
    )
    logger.info(
        "pipeline %s activity rescheduled after late retry batch anchor=%s new_at=%s",
        row.pipeline_id,
        anchor,
        new_at,
    )
    return True


def augment_late_retry_eligibility(row, eligibility: dict[str, Any]) -> dict[str, Any]:
    """
    启用延期策略时：等活动阶段始终允许发起补跑（不再因原预约时间已过而拒绝）。
    """
    if not is_defer_policy_enabled(row):
        return eligibility
    out = dict(eligibility)
    status = str(getattr(row, "status", "") or "")
    step = str(getattr(row, "current_step", "") or "")
    if status not in {"waiting_activity", "running"} or step != "waiting_activity":
        return out
    if not getattr(row, "scheduled_activity_at", None) and not getattr(row, "campaign_run_id", None):
        return out

    from pdd_agent.api.services.pipeline_late_retry_policy import (
        ACTIVE_PHASES,
        late_retry_state,
        list_failed_selectors,
    )

    state = late_retry_state(row)
    phase = str(state.get("phase") or "")
    if phase in ACTIVE_PHASES:
        out["eligible"] = False
        out["reason"] = "late_retry_in_progress"
        out["phase"] = phase
        return out

    failed = list_failed_selectors(row)
    if not failed:
        out["eligible"] = False
        out["reason"] = "no_failed_selectors"
        return out

    scheduled = getattr(row, "scheduled_activity_at", None)
    out["eligible"] = True
    out["reason"] = ""
    out["failed_selectors"] = failed
    out["failed_count"] = len(failed)
    out["activity_defer_enabled"] = True
    if isinstance(scheduled, datetime):
        remaining = (scheduled - datetime.now()).total_seconds() / 60.0
        out["minutes_remaining"] = round(remaining, 1)
        out["activity_deadline_at"] = scheduled.isoformat()
    return out

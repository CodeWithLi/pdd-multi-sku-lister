"""
RabbitMQ 自动上架 — 多店铺串行 + 延迟阶段二（活动/推广）。

阶段一：各店铺串行完成「上架 + 限时限量购」，记录完成时间与活动到期时间。
阶段二：定时任务按到期时间串行启动活动/推广；限时失败则跳过活动、仅跑推广。
状态持久化在 integrated_pipelines.meta（MySQL），便于查询与恢复。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    get_integrated_pipeline,
    list_mq_auto_phase2_due_pipelines,
    update_integrated_pipeline,
)
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)

META_DEFERRED_KEY = "mq_auto_deferred_phase2"
META_PHASE2_STATUS = "mq_phase2_status"
META_SKIP_ACTIVITY = "mq_skip_activity"
META_PHASE1_AT = "phase1_completed_at"
META_PHASE2_DUE = "phase2_due_at"
STEP_WAITING = "waiting_mq_phase2"
PHASE2_PENDING = "pending"
PHASE2_RUNNING = "running"
PHASE2_COMPLETED = "completed"


def is_mq_auto_deferred_phase2_row(row) -> bool:
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    return bool(meta.get(META_DEFERRED_KEY))


def compute_mq_phase2_due_at(row, *, completed_at: datetime | None = None) -> datetime:
    """跑完上架+限时后，活动/推广最早可启动时间（整数小时，无抖动）。"""
    from pdd_agent.api.services.pipeline_service import _resolve_activity_delay

    completed_at = completed_at or datetime.now()
    if bool(getattr(row, "demo_mode", False)):
        delta = _resolve_activity_delay(
            demo_mode=True,
            activity_delay_hours=float(getattr(row, "activity_delay_hours", 24) or 24),
        )
        return completed_at + delta
    hours = max(1, int(float(getattr(row, "activity_delay_hours", 24) or 24)))
    return completed_at + timedelta(hours=hours)


def _summarize_run_message(run_id: str) -> str:
    record = TaskRunStore().load(run_id)
    return str(record.message or "") if record else ""


def record_mq_phase1_complete(
    row,
    *,
    limited_time_success: bool,
    run_id: str,
    error: str = "",
    advance_store_sequential_fn: Callable[[Any], None] | None = None,
) -> None:
    """记录阶段一完成，等待定时任务触发活动/推广。"""
    now = datetime.now()
    due_at = compute_mq_phase2_due_at(row, completed_at=now)
    skip_activity = not limited_time_success

    meta_patch: dict[str, Any] = {
        "limited_time_finish_handled": True,
        "limited_time_summary": _summarize_run_message(run_id),
        "limited_time_outcome": "success" if limited_time_success else "failed",
        META_PHASE1_AT: now.isoformat(),
        META_PHASE2_DUE: due_at.isoformat(),
        META_PHASE2_STATUS: PHASE2_PENDING,
        META_SKIP_ACTIVITY: skip_activity,
    }
    if skip_activity:
        meta_patch["limited_time_skip_reason"] = error or "限时限量购设置失败"

    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step=STEP_WAITING,
        scheduled_activity_at=due_at,
        error="" if limited_time_success else "",
        meta_patch=meta_patch,
    )
    logger.info(
        "mq auto phase1 done pipeline=%s account=%s lt_success=%s due_at=%s skip_activity=%s",
        row.pipeline_id,
        row.account_id,
        limited_time_success,
        due_at,
        skip_activity,
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    from pdd_agent.api.services.pipeline_mq_auto_commerce import release_mq_store_after_phase1

    release_mq_store_after_phase1(refreshed)
    if advance_store_sequential_fn:
        advance_store_sequential_fn(refreshed)


def handle_mq_auto_limited_time_finished(
    row,
    *,
    run_id: str,
    success: bool,
    error: str,
    advance_store_sequential_fn: Callable[[Any], None],
) -> bool:
    """限时限量购结束且为 MQ 延迟阶段二模式时处理；返回 True 表示已接管。"""
    if not is_mq_auto_deferred_phase2_row(row):
        return False

    meta = row.meta if isinstance(row.meta, dict) else {}
    if meta.get("limited_time_finish_handled") and str(row.current_step or "") == STEP_WAITING:
        advance_store_sequential_fn(row)
        return True

    record_mq_phase1_complete(
        row,
        limited_time_success=success,
        run_id=run_id,
        error=error,
        advance_store_sequential_fn=advance_store_sequential_fn,
    )
    return True


def _is_phase2_still_running(row) -> bool:
    meta = row.meta if isinstance(row.meta, dict) else {}
    if meta.get(META_PHASE2_STATUS) != PHASE2_RUNNING:
        return False
    step = str(row.current_step or "")
    if step in {"completed", "failed", "canceled"}:
        return False
    if row.traffic_run_id:
        from pdd_agent.domain.enums import RunStatus

        record = TaskRunStore().load(row.traffic_run_id)
        if record:
            status = str(record.status.value if hasattr(record.status, "value") else record.status)
            if status in {RunStatus.SUCCESS.value, RunStatus.FAILED.value, RunStatus.CANCELED.value}:
                return False
    if row.campaign_run_id and not row.traffic_run_id:
        from pdd_agent.domain.enums import RunStatus

        record = TaskRunStore().load(row.campaign_run_id)
        if record:
            status = str(record.status.value if hasattr(record.status, "value") else record.status)
            if status in {RunStatus.SUCCESS.value, RunStatus.FAILED.value, RunStatus.CANCELED.value}:
                return False
    return True


def find_mq_phase2_running_pipeline():
    from pdd_agent.db.repositories import list_mq_auto_phase2_running_pipelines

    for row in list_mq_auto_phase2_running_pipelines(limit=20):
        if _is_phase2_still_running(row):
            return row
        mark_mq_phase2_completed(row)
    return None


def mark_mq_phase2_completed(row) -> None:
    update_integrated_pipeline(
        row.pipeline_id,
        meta_patch={META_PHASE2_STATUS: PHASE2_COMPLETED},
    )


def start_mq_phase2(row) -> dict[str, Any]:
    """启动单店阶段二：活动（限时成功时）→ 推广。"""
    from pdd_agent.api.services.pipeline_mq_auto_commerce import (
        assess_mq_phase2_account_idle,
        clear_mq_phase2_wait_for_account_idle,
    )
    from pdd_agent.api.services.pipeline_service import (
        _enqueue_pipeline_traffic,
        _schedule_pipeline_campaign,
    )

    pipeline_id = str(row.pipeline_id or "").strip()
    account_id = str(row.account_id or "").strip()
    assessment = assess_mq_phase2_account_idle(account_id=account_id, pipeline_id=pipeline_id)
    if not assessment.get("ready"):
        return {
            "pipeline_id": pipeline_id,
            "started": False,
            "deferred": True,
            "reason": assessment.get("reason"),
            "detail": assessment.get("detail"),
        }

    clear_mq_phase2_wait_for_account_idle(pipeline_id)

    meta = dict(row.meta or {})
    skip_activity = bool(meta.get(META_SKIP_ACTIVITY))

    update_integrated_pipeline(
        pipeline_id,
        status="running",
        current_step="mq_phase2_running",
        meta_patch={META_PHASE2_STATUS: PHASE2_RUNNING},
    )
    refreshed = get_integrated_pipeline(pipeline_id) or row

    if skip_activity:
        meta_patch: dict[str, Any] = {
            "campaign_outcome": "limited_time_failed_skip_activity",
            "campaign_skip_reason": str(meta.get("limited_time_skip_reason") or "限时限量购失败，跳过活动报名"),
        }
        update_integrated_pipeline(
            pipeline_id,
            current_step="limited_time_failed_continue",
            meta_patch=meta_patch,
        )
        refreshed = get_integrated_pipeline(pipeline_id) or row
        if refreshed.auto_promotion:
            _enqueue_pipeline_traffic(refreshed, meta_patch=meta_patch)
            logger.info("mq auto phase2 promotion-only pipeline=%s account=%s", pipeline_id, refreshed.account_id)
            return {"pipeline_id": pipeline_id, "mode": "promotion_only", "started": True}
        mark_mq_phase2_completed(refreshed)
        update_integrated_pipeline(
            pipeline_id,
            status="completed",
            current_step="completed",
            error="",
        )
        return {"pipeline_id": pipeline_id, "mode": "completed_no_promotion", "started": True}

    _schedule_pipeline_campaign(
        refreshed,
        activity_index=0,
        scheduled_at=datetime.now(),
        meta_patch={META_PHASE2_STATUS: PHASE2_RUNNING},
    )
    logger.info("mq auto phase2 activity+promotion pipeline=%s account=%s", pipeline_id, refreshed.account_id)
    return {"pipeline_id": pipeline_id, "mode": "activity_then_promotion", "started": True}


def tick_mq_auto_phase2(*, limit: int = 1) -> dict[str, Any]:
    """定时任务入口：串行处理已到期的阶段二；店铺未空闲则顺延，不取消。"""
    from pdd_agent.api.services.pipeline_mq_auto_commerce import record_mq_phase2_wait_for_account_idle

    summary: dict[str, Any] = {"processed": 0, "started": [], "deferred": []}
    running = find_mq_phase2_running_pipeline()
    if running:
        summary["skipped"] = "phase2_running"
        summary["running_pipeline_id"] = running.pipeline_id
        return summary

    due_rows = list_mq_auto_phase2_due_pipelines(limit=max(10, limit * 5))
    if not due_rows:
        return summary

    for row in due_rows:
        if summary["processed"] >= max(1, limit):
            break
        try:
            result = start_mq_phase2(row)
            if result.get("deferred"):
                record_mq_phase2_wait_for_account_idle(row, result)
                summary["deferred"].append(
                    {
                        "pipeline_id": result.get("pipeline_id"),
                        "account_id": row.account_id,
                        "reason": result.get("reason"),
                        "detail": result.get("detail"),
                    }
                )
                continue
            summary["processed"] += 1
            summary["started"].append(result)
        except Exception:
            logger.exception("mq auto phase2 start failed pipeline=%s", row.pipeline_id)
    return summary


def maybe_complete_mq_phase2_on_traffic_finished(row) -> None:
    """推广或活动链结束后标记阶段二结束。"""
    maybe_complete_mq_phase2(row)


def maybe_complete_mq_phase2(row) -> None:
    if not is_mq_auto_deferred_phase2_row(row):
        return
    meta = row.meta if isinstance(row.meta, dict) else {}
    if meta.get(META_PHASE2_STATUS) == PHASE2_RUNNING:
        mark_mq_phase2_completed(row)

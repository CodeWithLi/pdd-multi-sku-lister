"""
分批限时限量购重跑 — 与主链路 / 队列的桥接。

仅在 pipeline_service、task_queue、pipelines 路由中引用，避免散落修改。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)


def dispatch_batch_limited_time_retry_queue_task_finished(
    row,
    *,
    agent: str,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    """队列任务结束：优先处理分批限时重跑（含 failed 链路复活）。"""
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        dispatch_batch_limited_time_retry_queue_task_finished as _dispatch,
        is_batch_limited_time_retry_run,
    )

    if not is_batch_limited_time_retry_run(row, run_id):
        return False
    return _dispatch(
        row,
        agent=agent,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )


def maybe_defer_activity_task_execution(row, *, task_id: str, run_id: str) -> bool:
    """活动任务执行前：分批限时重跑进行中则推迟。"""
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
        maybe_defer_activity_task_execution as _batch_defer,
    )
    from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
        maybe_defer_activity_task_execution as _late_defer,
    )

    if _batch_defer(row, task_id=task_id, run_id=run_id):
        return True
    return _late_defer(row, task_id=task_id, run_id=run_id)


def build_batch_limited_time_retry_public_state(row) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        build_batch_limited_time_retry_public_state as _build,
    )

    return _build(row)


def evaluate_batch_limited_time_retry_eligibility(row, batch_index: int) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        evaluate_batch_limited_time_retry_eligibility as _evaluate,
    )

    return _evaluate(row, batch_index)


def start_batch_limited_time_retry(pipeline_id: str, *, batch_index: int) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        start_batch_limited_time_retry as _start,
    )

    return _start(pipeline_id, batch_index=batch_index)


def maybe_flush_batch_lt_retry_activity_reschedule(row) -> bool:
    """首轮限时全部结束后，补执行此前分批重跑积压的活动改期。"""
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
        maybe_finalize_activity_after_batch_lt_retry,
    )

    refreshed = row
    if refreshed is None:
        return False
    return maybe_finalize_activity_after_batch_lt_retry(refreshed)


def reconcile_revived_failed_pipeline(row):
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
        reconcile_revived_failed_pipeline as _reconcile,
    )

    return _reconcile(row)


def should_absorb_traffic_failure_after_batch_lt_revive(row, run_id: str) -> bool:
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
        should_absorb_traffic_failure_after_batch_lt_revive as _should,
    )

    return _should(row, run_id)

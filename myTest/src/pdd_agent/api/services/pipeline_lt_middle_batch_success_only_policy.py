"""
可选策略：「仅限时成功报活动」+「分批每批限时限量购」。

中间批限时失败时，不应交给 success_only 收尾把整条链路标 failed，而应继续下一批上架。

回滚方式：
  1. 删除 pipeline_service._on_limited_time_finished 内对本模块的引用；或
  2. 在链路 meta 中设置 pipeline_lt_middle_batch_success_only_policy_enabled=false。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, update_integrated_pipeline

logger = get_logger(__name__)

POLICY_META_FLAG = "pipeline_lt_middle_batch_success_only_policy_enabled"


def is_policy_enabled(row) -> bool:
    """默认启用；meta 显式设为 false 时关闭（无需改 pipeline_service）。"""
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    if POLICY_META_FLAG in meta:
        return bool(meta[POLICY_META_FLAG])
    return True


def should_skip_success_only_limited_time_finish(row) -> bool:
    """
    是否应阻止 handle_pipeline_limited_time_finished_for_activity 在中间批收尾。

    仅当：策略启用 + 仅限时成功报活动 + 分批每批限时 + 仍有后续上架批次。
    """
    if not row or not is_policy_enabled(row):
        return False

    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        is_activity_limited_time_success_only_row,
    )
    from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
        has_pending_throttled_listing_batches,
        is_per_batch_limited_time_pipeline,
    )
    from pdd_agent.api.services.pipeline_per_batch_limited_time import _per_batch_state

    if not is_activity_limited_time_success_only_row(row):
        return False
    if not is_per_batch_limited_time_pipeline(row):
        return False
    if dict(_per_batch_state(row)).get("awaiting_final_activity"):
        return False
    return has_pending_throttled_listing_batches(row)


def _rebuild_pending_from_throttle(row) -> dict[str, Any] | None:
    from pdd_agent.api.services.pipeline_listing_throttle import has_more_listing_batches
    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        _per_batch_batch_log_context,
        _throttle_state,
    )

    throttle = _throttle_state(row)
    batch_index = int(throttle.get("batch_index") or 0)
    if not has_more_listing_batches(throttle):
        logger.info(
            "pipeline %s middle-batch LT rebuild pending skipped: no more batches ctx=%s",
            row.pipeline_id,
            _per_batch_batch_log_context(row),
        )
        return None
    pending = {
        "next_batch_index": batch_index + 1,
        "interval_minutes": max(1, int(throttle.get("interval_minutes") or 1)),
    }
    logger.warning(
        "pipeline %s middle-batch LT rebuild pending from throttle batch_index=%s -> next_batch_index=%s ctx=%s",
        row.pipeline_id,
        batch_index,
        pending["next_batch_index"],
        _per_batch_batch_log_context(row),
    )
    return pending


def _ensure_per_batch_continue_ready(row, *, run_id: str):
    """对齐 limited_time_run_id / pending，便于 maybe_continue 接管。"""
    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        META_STATE_KEY,
        _per_batch_state,
        _per_batch_batch_log_context,
        is_per_batch_limited_time_continue_handled,
    )
    from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
        pipeline_limited_time_run_id,
    )

    meta_patch: dict[str, Any] = {}
    rid = str(run_id or "").strip()
    if rid and pipeline_limited_time_run_id(row) != rid:
        logger.warning(
            "pipeline %s middle-batch LT sync limited_time_run_id %s -> %s ctx=%s",
            row.pipeline_id,
            pipeline_limited_time_run_id(row),
            rid,
            _per_batch_batch_log_context(row),
        )
        meta_patch["limited_time_run_id"] = rid

    state = dict(_per_batch_state(row))
    if not state.get("pending"):
        if is_per_batch_limited_time_continue_handled(row, run_id):
            logger.info(
                "pipeline %s middle-batch LT ensure ready skip rebuild: continue already handled run_id=%s ctx=%s",
                row.pipeline_id,
                rid,
                _per_batch_batch_log_context(row),
            )
            return row
        pending = _rebuild_pending_from_throttle(row)
        if pending:
            meta_patch[META_STATE_KEY] = {
                **state,
                "enabled": True,
                "awaiting_final_activity": False,
                "pending": pending,
            }
            logger.warning(
                "pipeline %s middle-batch LT policy rebuilt pending next_batch_index=%s",
                row.pipeline_id,
                pending.get("next_batch_index"),
            )

    if not meta_patch:
        return row

    update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)
    return get_integrated_pipeline(row.pipeline_id) or row


def _continue_next_listing_batch_relaxed(
    row,
    *,
    run_id: str,
    success: bool,
    error: str,
) -> bool:
    """
    在 maybe_continue 仍失败时的兜底：按 throttle 直接预约下一批上架（跳过 run_id 校验）。
    """
    from pdd_agent.api.services.pipeline_listing_throttle import enqueue_listing_batch_for_pipeline
    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        META_STATE_KEY,
        _per_batch_state,
        _per_batch_batch_log_context,
        _throttle_state,
        mark_per_batch_limited_time_continue_handled,
    )

    pending = dict(_per_batch_state(row).get("pending") or {})
    if not pending:
        pending = _rebuild_pending_from_throttle(row) or {}
    if not pending:
        return False

    throttle = _throttle_state(row)
    batches = list(throttle.get("batches") or [])
    next_index = int(pending.get("next_batch_index") or 0)
    if next_index < 0 or next_index >= len(batches):
        logger.warning(
            "pipeline %s middle-batch LT policy pending index out of range: %s",
            row.pipeline_id,
            next_index,
        )
        return False

    failure_message = str(error or "").strip() or "限时限量购设置失败"
    lt_failure_meta: dict[str, Any] = {
        "limited_time_outcome": "failed",
        "per_batch_limited_time_last_error": failure_message,
    }
    if rid := str(run_id or "").strip():
        lt_failure_meta["limited_time_run_id"] = rid

    state = dict(_per_batch_state(row))
    if not success:
        logger.warning(
            "pipeline %s middle-batch LT policy relaxed continue batch=%s error=%s",
            row.pipeline_id,
            int(state.get("last_batch_index") or throttle.get("batch_index") or 0) + 1,
            failure_message,
        )
        update_integrated_pipeline(
            row.pipeline_id,
            status="running",
            current_step="waiting_limited_time_per_batch",
            error="",
            meta_patch=lt_failure_meta,
        )

    interval_minutes = max(
        1,
        int(pending.get("interval_minutes") or throttle.get("interval_minutes") or 1),
    )
    scheduled_at = datetime.now() + timedelta(minutes=interval_minutes)
    payload_base = dict(throttle.get("listing_payload_base") or {})
    meta_patch: dict[str, Any] = {
        META_STATE_KEY: {
            **state,
            "enabled": True,
            "awaiting_final_activity": False,
            "pending": None,
        },
        "listing_throttle": {
            **throttle,
            "batch_index": next_index,
        },
    }
    update_integrated_pipeline(
        row.pipeline_id,
        current_step=f"waiting_listing_batch_{next_index + 1}",
        meta_patch=meta_patch,
    )
    enqueue_listing_batch_for_pipeline(
        pipeline_id=row.pipeline_id,
        account_id=row.account_id,
        batch_codes=list(batches[next_index]),
        listing_payload_base=payload_base,
        scheduled_at=scheduled_at,
    )
    mark_per_batch_limited_time_continue_handled(row, run_id)
    logger.info(
        "pipeline %s middle-batch LT policy relaxed scheduled listing batch %s/%s at %s "
        "run_id=%s batch_index %s->%s pending_was=%s ctx=%s",
        row.pipeline_id,
        next_index + 1,
        len(batches),
        scheduled_at,
        str(run_id or "").strip(),
        int(throttle.get("batch_index") or 0),
        next_index,
        pending,
        _per_batch_batch_log_context(row),
    )
    return True


def maybe_handle_middle_batch_before_success_only_finish(
    row,
    *,
    run_id: str,
    success: bool,
    error: str = "",
) -> bool:
    """
    在 success_only 收尾前调用。若已接管后续（继续下一批上架）返回 True。

    pipeline_service 仅需引用此函数；删除引用即可回滚。
    """
    if not should_skip_success_only_limited_time_finish(row):
        return False

    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        _per_batch_batch_log_context,
        maybe_continue_after_per_batch_limited_time,
    )

    logger.info(
        "pipeline %s middle-batch LT policy enter run_id=%s success=%s error=%s ctx=%s",
        row.pipeline_id,
        str(run_id or "").strip(),
        success,
        str(error or "").strip()[:200],
        _per_batch_batch_log_context(row),
    )

    refreshed = _ensure_per_batch_continue_ready(row, run_id=run_id)
    rid = str(run_id or "").strip()

    if maybe_continue_after_per_batch_limited_time(
        refreshed,
        run_id=rid,
        success=success,
        error=error,
    ):
        logger.info(
            "pipeline %s middle-batch LT policy continued via maybe_continue run_id=%s",
            refreshed.pipeline_id,
            rid,
        )
        return True

    refreshed = get_integrated_pipeline(refreshed.pipeline_id) or refreshed
    if _continue_next_listing_batch_relaxed(
        refreshed,
        run_id=rid,
        success=success,
        error=error,
    ):
        return True

    logger.error(
        "pipeline %s middle-batch LT policy could not schedule next listing batch run_id=%s",
        refreshed.pipeline_id,
        rid,
    )
    return False

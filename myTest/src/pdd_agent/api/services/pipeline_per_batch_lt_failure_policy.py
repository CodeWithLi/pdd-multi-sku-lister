"""
分批限时限量购失败策略（与 pipeline_service / 串行店铺隔离）。

目标：
- 中间批次限时限量购失败：记录错误，继续下一批上架，不把整条链路标 failed。
- 全部批次未完成时：不触发「串行下一家店铺」。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)


def is_per_batch_limited_time_pipeline(row) -> bool:
    if not row:
        return False
    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        _should_handle,
        is_per_batch_limited_time_enabled,
    )

    if not is_per_batch_limited_time_enabled(row):
        return False
    return _should_handle(row)


def has_pending_throttled_listing_batches(row) -> bool:
    """是否仍有未跑完的分批上架（含已预约的下一批）。"""
    if not row:
        return False
    meta = dict(row.meta or {})
    throttle = dict(meta.get("listing_throttle") or {})
    if not throttle.get("enabled"):
        return False

    from pdd_agent.api.services.pipeline_listing_throttle import has_more_listing_batches
    from pdd_agent.api.services.pipeline_per_batch_limited_time import _per_batch_state

    if has_more_listing_batches(throttle):
        return True

    lt_state = dict(_per_batch_state(row))
    if lt_state.get("pending"):
        return True

    step = str(row.current_step or "")
    if step.startswith("waiting_listing_batch_"):
        return True
    if step in {"waiting_limited_time_per_batch", "listing_queued"} and not throttle.get("completed"):
        batch_index = int(throttle.get("batch_index") or 0)
        total = int(throttle.get("total_batches") or 0)
        if total > 0 and batch_index + 1 < total:
            return True
    return False


def pipeline_limited_time_run_id(row) -> str:
    return str((row.meta or {}).get("limited_time_run_id") or "").strip()


def continue_after_limited_time_failure_enabled(row) -> bool:
    return bool((row.meta or {}).get("continue_after_limited_time_failure"))


def should_absorb_per_batch_limited_time_failure(row, *, run_id: str = "") -> bool:
    """
    本批限时限量购失败时，是否不应把整合链路标为 failed。

    - 分批 + 仍有后续上架批次：始终吸收（失败仅记 meta，继续下一批）。
    - 最后一批：遵从 continue_after_limited_time_failure 开关。
  - 非分批：仅当 continue_after_limited_time_failure 开启时吸收。
    """
    if not row:
        return False
    rid = str(run_id or "").strip()
    if rid and pipeline_limited_time_run_id(row) != rid:
        return False

    if is_per_batch_limited_time_pipeline(row):
        if has_pending_throttled_listing_batches(row):
            return True
        return continue_after_limited_time_failure_enabled(row)

    return continue_after_limited_time_failure_enabled(row)


def build_per_batch_limited_time_failure_meta(error: str) -> dict[str, Any]:
    message = str(error or "").strip() or "限时限量购设置失败"
    return {
        "limited_time_outcome": "failed",
        "per_batch_limited_time_last_error": message,
        "limited_time_skip_reason": message,
    }


def should_block_sequential_store_advance(row) -> bool:
    """
    分批上架/每批限时限量购未完成时，不启动串行队列中的下一家店铺。
    """
    if not row:
        return False
    if not is_per_batch_limited_time_pipeline(row):
        return False
    if has_pending_throttled_listing_batches(row):
        logger.info(
            "sequential store advance blocked: listing batches still pending pipeline=%s step=%s",
            row.pipeline_id,
            row.current_step,
        )
        return True
    return False


def log_absorbed_limited_time_failure(row, *, run_id: str, error: str) -> None:
    throttle = dict((row.meta or {}).get("listing_throttle") or {})
    batch_index = int(throttle.get("batch_index") or 0) + 1
    total = int(throttle.get("total_batches") or 0)
    logger.warning(
        "pipeline %s per-batch limited time failed batch=%s/%s run_id=%s error=%s; continue listing batches",
        row.pipeline_id,
        batch_index,
        total,
        run_id,
        str(error or "").strip() or "限时限量购设置失败",
    )

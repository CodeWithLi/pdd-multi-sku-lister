"""分批限时重跑 — 上架完成 / 首轮限时完成 判定。"""

from __future__ import annotations

from typing import Any


def is_pipeline_listing_batches_complete(row) -> bool:
    """全部分批上架已结束（不要求首轮限时限量购全部跑完）。"""
    if not row:
        return False
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    throttle = dict(meta.get("listing_throttle") or {})
    step = str(getattr(row, "current_step", "") or "")

    if step.startswith("waiting_listing_batch_"):
        return False

    if throttle.get("enabled"):
        if throttle.get("completed"):
            return True
        from pdd_agent.api.services.pipeline_listing_throttle import has_more_listing_batches

        if not has_more_listing_batches(throttle):
            return True
        batch_index = int(throttle.get("batch_index") or 0)
        total = int(throttle.get("total_batches") or 0)
        if total > 0 and batch_index + 1 >= total:
            return True
        return False

    if step in {"listing_queued", "listing_running"}:
        return False
    listing_outcome = str(meta.get("listing_outcome") or "").strip()
    if listing_outcome in {"success", "partial_success", "skipped"}:
        return True
    listing_step_done = step not in {
        "listing_queued",
        "listing_running",
        "waiting_listing_batch",
    }
    return listing_step_done and bool(getattr(row, "listing_run_id", None))


def is_pipeline_initial_limited_time_phase_complete(row) -> bool:
    """全部批次的首轮限时限量购已记录完成（活动改期需在此之后）。"""
    if not row:
        return False
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.constants import (
        AGG_BATCH_COUNT_KEY,
        AGG_BATCH_LOG_KEY,
        AGG_FINALIZED_KEY,
        AGG_IN_PROGRESS_KEY,
    )

    if meta.get(AGG_FINALIZED_KEY):
        return True
    if meta.get("limited_time_finish_handled"):
        return True

    throttle = dict(meta.get("listing_throttle") or {})
    total_batches = int(throttle.get("total_batches") or 0)
    batch_log = meta.get(AGG_BATCH_LOG_KEY) or []
    logged_batches = len(batch_log) if isinstance(batch_log, list) else 0
    if total_batches > 0 and logged_batches >= total_batches:
        return True
    if logged_batches > 0 and not meta.get(AGG_IN_PROGRESS_KEY):
        if total_batches <= 0 or logged_batches >= total_batches:
            return True

    step = str(getattr(row, "current_step", "") or "")
    status = str(getattr(row, "status", "") or "")
    if step in {
        "waiting_activity",
        "limited_time_failed",
        "limited_time_failed_continue",
        "limited_time_success_continue",
        "activity_failed",
        "campaign_queued",
        "batch_limited_time_retry",
        "completed",
    }:
        return True
    if status in {"waiting_activity", "failed"} and step == "limited_time_failed":
        return True
    return False


def is_batch_initial_limited_time_recorded(products: list[dict[str, Any]]) -> bool:
    """本批至少有一个上架成功商品已完成首轮限时（成功/失败/跳过）。"""
    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import STAGE_PENDING, STAGE_SUCCESS

    for item in products:
        if str(item.get("listing_status") or "") != STAGE_SUCCESS:
            continue
        lt_status = str(item.get("limited_time_status") or "").strip()
        if lt_status and lt_status != STAGE_PENDING:
            return True
    return False

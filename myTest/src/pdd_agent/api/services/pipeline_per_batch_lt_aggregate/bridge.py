"""pipeline_service 薄桥接 — 标准分批限时聚合进度。"""

from __future__ import annotations

from typing import Any

from pdd_agent.api.services.pipeline_per_batch_lt_aggregate import orchestrator

is_standard_per_batch_lt_pipeline = orchestrator.is_standard_per_batch_lt_pipeline


def maybe_record_listing_batch(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_result: dict[str, Any] | None,
) -> None:
    orchestrator.record_listing_batch(
        row,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        listing_result=listing_result,
    )


def record_limited_time_batch_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
):
    return orchestrator.record_limited_time_batch_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )


def record_skipped_limited_time_batch_for_empty_listing(
    row,
    *,
    skip_reason: str = "本批无成功上架商品",
) -> bool:
    return orchestrator.record_skipped_limited_time_batch_for_empty_listing(
        row,
        skip_reason=skip_reason,
    )


def backfill_missing_limited_time_batches(row) -> bool:
    return orchestrator.backfill_missing_limited_time_batches(row)


def restore_intermediate_lt_progress_meta(row) -> None:
    orchestrator.restore_intermediate_lt_progress_meta(row)


def maybe_finalize_after_all_batches(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
    schedule_activity_fn,
    advance_store_sequential_fn,
    summarize_run_message_fn,
) -> bool:
    return orchestrator.maybe_finalize_after_all_batches(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
        schedule_activity_fn=schedule_activity_fn,
        advance_store_sequential_fn=advance_store_sequential_fn,
        summarize_run_message_fn=summarize_run_message_fn,
    )


def should_absorb_limited_time_task_failure(row, *, agent: str, run_id: str, success: bool) -> bool:
    if success:
        return False
    if str(agent or "").strip() != "campaign":
        return False
    return orchestrator.should_absorb_limited_time_task_failure(row, run_id=run_id)


def resolve_limited_time_step_display(row) -> dict[str, Any] | None:
    return orchestrator.resolve_limited_time_step_display(row)


def maybe_record_campaign_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> None:
    orchestrator.record_campaign_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )


def maybe_record_traffic_finished(
    row,
    *,
    run_id: str,
    success: bool,
    error: str,
    result: dict[str, Any] | None = None,
) -> None:
    orchestrator.record_traffic_finished(
        row,
        run_id=run_id,
        success=success,
        error=error,
        result=result,
    )

"""pipeline_service / per_batch_limited_time / retry 薄桥接。"""

from __future__ import annotations

from typing import Any

from pdd_agent.api.services.pipeline_per_batch_lt_chunks import orchestrator

is_standard_per_batch_lt_chunk_pipeline = orchestrator.is_standard_per_batch_lt_chunk_pipeline
resolve_chunk_size = orchestrator.resolve_chunk_size
per_batch_lt_chunks_meta_patch = orchestrator.per_batch_lt_chunks_meta_patch
is_limited_time_chunk_sequence_active = orchestrator.is_limited_time_chunk_sequence_active
resolve_limited_time_step_chunk_hint = orchestrator.resolve_limited_time_step_chunk_hint


def maybe_start_chunked_limited_time_after_listing(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_meta: dict[str, Any] | None,
) -> bool:
    return orchestrator.maybe_start_chunked_limited_time_after_listing(
        row,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        listing_meta=listing_meta,
    )


def maybe_start_chunked_batch_limited_time_retry(
    row,
    *,
    batch_index: int,
    pdd_ids: list[str],
    mapping_ids: list[str],
) -> str | None:
    return orchestrator.maybe_start_chunked_batch_limited_time_retry(
        row,
        batch_index=batch_index,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    )


def maybe_handle_limited_time_chunk_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    return orchestrator.maybe_handle_limited_time_chunk_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )


def should_skip_aggregate_for_incomplete_chunks(row, *, run_id: str) -> bool:
    return orchestrator.should_skip_aggregate_for_incomplete_chunks(row, run_id=run_id)


def should_skip_lt_batch_tracker_for_aggregate(row, *, run_id: str) -> bool:
    return orchestrator.should_skip_lt_batch_tracker_for_aggregate(row, run_id=run_id)


def clear_lt_batch_tracker_aggregate_flag(row) -> None:
    orchestrator.clear_lt_batch_tracker_aggregate_flag(row)


def consume_chunk_retry_finish_context(row) -> dict[str, Any] | None:
    return orchestrator.consume_chunk_retry_finish_context(row)


def merge_chunk_retry_success_into_activity_pool(
    row,
    *,
    lt_success_pdd: list[str],
    lt_success_mapping: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    return orchestrator.merge_chunk_retry_success_into_activity_pool(
        row,
        lt_success_pdd=lt_success_pdd,
        lt_success_mapping=lt_success_mapping,
    )

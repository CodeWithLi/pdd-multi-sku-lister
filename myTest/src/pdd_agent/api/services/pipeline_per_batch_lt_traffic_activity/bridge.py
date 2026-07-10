"""pipeline_service 薄桥接层 — 仅转发至 orchestrator。"""

from __future__ import annotations

from typing import Any

from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity import orchestrator

per_batch_lt_traffic_activity_meta_patch = orchestrator.per_batch_lt_traffic_activity_meta_patch
is_per_batch_lt_traffic_activity_enabled = orchestrator.is_per_batch_lt_traffic_activity_enabled


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


def maybe_handle_limited_time_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    return orchestrator.handle_limited_time_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )


def maybe_handle_traffic_finished(
    row,
    *,
    run_id: str,
    success: bool,
    error: str,
    result: dict[str, Any] | None = None,
) -> bool:
    return orchestrator.handle_traffic_finished(
        row,
        run_id=run_id,
        success=success,
        error=error,
        result=result,
    )


def maybe_handle_campaign_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    return orchestrator.handle_campaign_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )


def should_absorb_queue_task_failure(row, *, agent: str, run_id: str, success: bool) -> bool:
    return orchestrator.should_absorb_task_failure(
        row,
        agent=agent,
        run_id=run_id,
        success=success,
    )

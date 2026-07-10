"""pipeline_service 薄桥接 — 活动/推广分批。"""

from __future__ import annotations

from typing import Any

from pdd_agent.api.services.pipeline_activity_traffic_batch import orchestrator

activity_traffic_batch_meta_patch = orchestrator.activity_traffic_batch_meta_patch
is_activity_traffic_batch_enabled = orchestrator.is_activity_traffic_batch_enabled
resolve_activity_traffic_batch_step_hint = orchestrator.resolve_activity_traffic_batch_step_hint


def maybe_start_after_limited_time(
    row,
    *,
    meta_patch: dict[str, Any] | None = None,
    pdd_ids: list[str] | None = None,
    mapping_ids: list[str] | None = None,
) -> bool:
    return orchestrator.maybe_start_after_limited_time(
        row,
        meta_patch=meta_patch,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    )


def maybe_handle_campaign_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    return orchestrator.maybe_handle_campaign_finished(
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
) -> bool:
    return orchestrator.maybe_handle_traffic_finished(
        row,
        run_id=run_id,
        success=success,
        error=error,
    )

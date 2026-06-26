"""
整合链路 — 分批上架：当前批全部失败时也继续下一批。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.api.services.pipeline_listing_throttle import (
    has_more_listing_batches,
    schedule_next_listing_batch_after_finish,
)
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, update_integrated_pipeline

logger = get_logger(__name__)

_CONTINUE_STEPS = frozenset(
    {
        "listing_queued",
        "waiting_limited_time_per_batch",
        "campaign_queued_per_batch",
        "traffic_queued_per_batch",
    }
)


def _throttle_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get("listing_throttle") or {})


def has_active_listing_throttle(row) -> bool:
    throttle = _throttle_state(row)
    return bool(throttle.get("enabled")) and int(throttle.get("total_batches") or 0) > 1


def has_remaining_listing_batch(row) -> bool:
    if not has_active_listing_throttle(row):
        return False
    return has_more_listing_batches(_throttle_state(row))


def is_listing_batch_failure_continuing(pipeline_id: str) -> bool:
    """子任务失败回调里：若已预约下一批，不要把整条链路标 failed。"""
    row = get_integrated_pipeline(str(pipeline_id or "").strip())
    if not row or row.status in {"failed", "completed", "canceled"}:
        return False
    step = str(row.current_step or "")
    if step.startswith("waiting_listing_batch_"):
        return True
    meta = dict(row.meta or {})
    if meta.get("listing_batch_failure_continued") and step in _CONTINUE_STEPS:
        return True
    return False


def _schedule_throttled_batch_followup(
    row,
    *,
    run_id: str,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_meta: dict[str, Any],
    batch_error: str = "",
) -> bool:
    from pdd_agent.api.services.pipeline_per_batch_campaign import (
        maybe_run_per_batch_campaign_after_listing,
    )
    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        maybe_run_per_batch_limited_time_after_listing,
    )

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    meta_patch = dict(listing_meta or {})
    meta_patch["listing_batch_failure_continued"] = True
    if batch_error:
        meta_patch["listing_batch_last_error"] = batch_error
    meta_patch["listing_batch_last_run_id"] = str(run_id or "").strip()

    if pdd_ids:
        if maybe_run_per_batch_limited_time_after_listing(
            refreshed,
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
            listing_meta=meta_patch,
        ):
            update_integrated_pipeline(
                refreshed.pipeline_id,
                status="running",
                error="",
                meta_patch=meta_patch,
            )
            return True
        if maybe_run_per_batch_campaign_after_listing(
            refreshed,
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
            listing_meta=meta_patch,
        ):
            update_integrated_pipeline(
                refreshed.pipeline_id,
                status="running",
                error="",
                meta_patch=meta_patch,
            )
            return True

    if schedule_next_listing_batch_after_finish(
        refreshed,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        listing_meta=meta_patch,
    ):
        update_integrated_pipeline(
            refreshed.pipeline_id,
            status="running",
            error="",
            meta_patch=meta_patch,
        )
        return True
    return False


def maybe_continue_listing_batch_after_failure(
    row,
    *,
    run_id: str,
    result: dict[str, Any] | None,
    error: str = "",
) -> bool:
    """
    当前批上架 run 失败时调用。若还有下一批且已预约，返回 True。
    """
    if not has_remaining_listing_batch(row):
        return False

    from pdd_agent.api.services.pipeline_service import (
        _extract_listing_products,
        _listing_failure_meta,
    )

    result = result if isinstance(result, dict) else {}
    pdd_ids, mapping_ids = _extract_listing_products(result)
    listing_meta = {
        "listing_summary": batch_error_summary(result, error),
    }
    listing_meta.update(_listing_failure_meta(result))

    batch_error = str(error or "").strip() or "本批上架全部失败"
    if _schedule_throttled_batch_followup(
        row,
        run_id=run_id,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        listing_meta=listing_meta,
        batch_error=batch_error,
    ):
        throttle = _throttle_state(get_integrated_pipeline(row.pipeline_id) or row)
        batch_index = int(throttle.get("batch_index") or 0)
        logger.info(
            "pipeline %s listing batch %s failed (%s), scheduled next batch",
            row.pipeline_id,
            batch_index + 1,
            batch_error,
        )
        return True
    return False


def batch_error_summary(result: dict[str, Any], error: str = "") -> str:
    err = str(error or "").strip()
    if err:
        return err
    errors = result.get("errors") or []
    if isinstance(errors, list):
        labels = [str(item or "").strip() for item in errors if str(item or "").strip()]
        if labels:
            return labels[0] if len(labels) == 1 else f"{len(labels)}套图有问题"
    return "本批上架失败"

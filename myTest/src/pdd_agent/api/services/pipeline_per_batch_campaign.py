"""
整合链路 — 分批上架后每批单独跑活动 / 推广。

可与「每批限时限量购」组合：
  上架 → [限时限量购] → 活动 → [推广] → 间隔 → 下一批上架
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.api.services.pipeline_listing_throttle import (
    enqueue_listing_batch_for_pipeline,
    has_more_listing_batches,
    merge_throttle_accumulated_products,
)
from pdd_agent.api.services.pipeline_per_batch_limited_time import (
    is_per_batch_limited_time_enabled,
)
from pdd_agent.api.services.task_runner import create_campaign_run, create_traffic_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import enqueue_task, get_integrated_pipeline, update_integrated_pipeline
from pdd_agent.domain.enums import AgentKind

logger = get_logger(__name__)

META_ENABLED_KEY = "listing_per_batch_campaign_enabled"
META_STATE_KEY = "listing_per_batch_campaign"


def per_batch_campaign_meta_patch(*, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {}
    return {META_ENABLED_KEY: True}


def is_per_batch_campaign_enabled(row) -> bool:
    return bool((row.meta or {}).get(META_ENABLED_KEY))


def _throttle_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get("listing_throttle") or {})


def _campaign_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get(META_STATE_KEY) or {})


def _should_handle(row) -> bool:
    if not is_per_batch_campaign_enabled(row):
        return False
    throttle = _throttle_state(row)
    if not throttle.get("enabled"):
        return False
    return int(throttle.get("total_batches") or 0) > 1


def _pipeline_activity_ids(row) -> list[str]:
    meta = dict(row.meta or {})
    ids = [str(item).strip() for item in (meta.get("activity_ids") or []) if str(item).strip()]
    if ids:
        return list(dict.fromkeys(ids))
    legacy = str(row.activity_id or "").strip()
    return [legacy] if legacy else []


def _pipeline_continue_after_activity_failure(row) -> bool:
    return bool((row.meta or {}).get("continue_after_activity_failure"))


def _pipeline_continue_after_limited_time_failure(row) -> bool:
    return bool((row.meta or {}).get("continue_after_limited_time_failure"))


def _pipeline_auto_limited_time(row) -> bool:
    return bool(_pipeline_activity_ids(row))


def _should_skip_campaign_for_traffic(result: dict[str, Any] | None, error: str | list | None = "") -> bool:
    from pdd_agent.api.services.pipeline_service import _should_skip_campaign_for_traffic as _skip

    return _skip(result, error)


def _build_batch_followup_state(
    *,
    batch_index: int,
    pdd_ids: list[str],
    mapping_ids: list[str],
    more_batches: bool,
    interval_minutes: int,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "enabled": True,
        "batch_index": batch_index,
        "batch_pdd_ids": list(pdd_ids),
        "batch_mapping_ids": list(mapping_ids),
        "activity_index": 0,
        "phase": "campaign",
        "is_final_batch": not more_batches,
    }
    if more_batches:
        state["pending_listing"] = {
            "next_batch_index": batch_index + 1,
            "next_batch_scheduled_at": (
                datetime.now() + timedelta(minutes=interval_minutes)
            ).isoformat(timespec="seconds"),
        }
    return state


def _merge_listing_meta(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_meta: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool, int]:
    throttle = _throttle_state(row)
    batch_index = int(throttle.get("batch_index") or 0)
    merged_pdd, merged_map = merge_throttle_accumulated_products(
        throttle,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    )
    more_batches = has_more_listing_batches(throttle)
    interval_minutes = max(1, int(throttle.get("interval_minutes") or 1))

    meta_patch = dict(listing_meta or {})
    meta_patch["listing_throttle"] = {
        **throttle,
        "accumulated_pdd_ids": merged_pdd,
        "accumulated_mapping_ids": merged_map,
    }
    if not more_batches:
        meta_patch["listing_throttle"]["batch_index"] = batch_index
        meta_patch["listing_throttle"]["completed"] = True

    campaign_state = _build_batch_followup_state(
        batch_index=batch_index,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        more_batches=more_batches,
        interval_minutes=interval_minutes,
    )
    meta_patch[META_STATE_KEY] = campaign_state
    return meta_patch, more_batches, batch_index


def _enqueue_campaign_for_batch(
    row,
    *,
    activity_index: int,
    pdd_ids: list[str],
    mapping_ids: list[str],
    meta_patch: dict[str, Any],
) -> str:
    activity_ids = _pipeline_activity_ids(row)
    if activity_index < 0 or activity_index >= len(activity_ids):
        raise ValueError("activity_index out of range")
    campaign_run_id = create_campaign_run(row.account_id)
    enqueue_task(
        agent=AgentKind.CAMPAIGN.value,
        run_id=campaign_run_id,
        account_id=row.account_id,
        payload={
            "pipeline_id": row.pipeline_id,
            "campaign_type": "marketing_activity_register",
            "activity_id": activity_ids[activity_index],
            "pdd_product_ids": list(pdd_ids),
        },
        scheduled_at=datetime.now(),
    )
    patch = dict(meta_patch or {})
    patch["campaign_activity_index"] = activity_index
    campaign_state = dict(patch.get(META_STATE_KEY) or _campaign_state(row))
    campaign_state["phase"] = "campaign"
    campaign_state["activity_index"] = activity_index
    patch[META_STATE_KEY] = campaign_state
    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="campaign_queued_per_batch",
        pdd_product_ids=list(pdd_ids),
        mapping_ids=list(mapping_ids),
        campaign_run_id=campaign_run_id,
        error="",
        meta_patch=patch,
    )
    return campaign_run_id


def _enqueue_traffic_for_batch(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    meta_patch: dict[str, Any],
) -> str:
    traffic_run_id = create_traffic_run(row.account_id)
    enqueue_task(
        agent=AgentKind.TRAFFIC.value,
        run_id=traffic_run_id,
        account_id=row.account_id,
        payload={
            "pipeline_id": row.pipeline_id,
            "traffic_type": "promotion_create",
            "pdd_product_ids": list(pdd_ids),
            "published_mapping_ids": list(mapping_ids),
        },
        scheduled_at=datetime.now(),
    )
    patch = dict(meta_patch or {})
    campaign_state = dict(patch.get(META_STATE_KEY) or _campaign_state(row))
    campaign_state["phase"] = "traffic"
    patch[META_STATE_KEY] = campaign_state
    patch["traffic_enqueued"] = True
    patch.pop("traffic_finish_handled", None)
    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="traffic_queued_per_batch",
        traffic_run_id=traffic_run_id,
        error="",
        meta_patch=patch,
    )
    return traffic_run_id


def _schedule_next_listing_batch(row, state: dict[str, Any]) -> bool:
    pending = dict(state.get("pending_listing") or {})
    if not pending:
        return False

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    throttle = _throttle_state(refreshed)
    batches = list(throttle.get("batches") or [])
    next_index = int(pending.get("next_batch_index") or 0)
    if next_index < 0 or next_index >= len(batches):
        logger.warning(
            "pipeline %s per-batch campaign pending batch index out of range: %s",
            row.pipeline_id,
            next_index,
        )
        return False

    scheduled_raw = str(pending.get("next_batch_scheduled_at") or "").strip()
    try:
        scheduled_at = datetime.fromisoformat(scheduled_raw) if scheduled_raw else datetime.now()
    except ValueError:
        scheduled_at = datetime.now()
    if scheduled_at < datetime.now():
        scheduled_at = datetime.now()

    payload_base = dict(throttle.get("listing_payload_base") or {})
    meta_patch = {
        META_STATE_KEY: {
            **state,
            "pending_listing": None,
            "phase": "done",
        },
        "listing_throttle": {
            **throttle,
            "batch_index": next_index,
        },
    }
    update_integrated_pipeline(
        refreshed.pipeline_id,
        current_step=f"waiting_listing_batch_{next_index + 1}",
        meta_patch=meta_patch,
    )
    enqueue_listing_batch_for_pipeline(
        pipeline_id=refreshed.pipeline_id,
        account_id=refreshed.account_id,
        batch_codes=list(batches[next_index]),
        listing_payload_base=payload_base,
        scheduled_at=scheduled_at,
    )
    logger.info(
        "pipeline %s per-batch campaign/traffic done, next listing batch %s/%s at %s",
        refreshed.pipeline_id,
        next_index + 1,
        len(batches),
        scheduled_at,
    )
    return True


def _complete_per_batch_pipeline(row, *, meta_patch: dict[str, Any] | None = None) -> None:
    patch = dict(meta_patch or {})
    campaign_state = dict(_campaign_state(row))
    campaign_state["phase"] = "done"
    patch[META_STATE_KEY] = campaign_state
    update_integrated_pipeline(
        row.pipeline_id,
        status="completed",
        current_step="completed",
        error="",
        meta_patch=patch,
    )
    logger.info("pipeline %s per-batch campaign flow completed", row.pipeline_id)


def _start_batch_campaign_chain(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    meta_patch: dict[str, Any],
) -> bool:
    if not _pipeline_activity_ids(row):
        return _advance_after_batch_steps(row, meta_patch=meta_patch)
    run_id = _enqueue_campaign_for_batch(
        row,
        activity_index=0,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        meta_patch=meta_patch,
    )
    logger.info(
        "pipeline %s per-batch campaign queued run_id=%s pdd_ids=%s",
        row.pipeline_id,
        run_id,
        pdd_ids,
    )
    return True


def _advance_after_batch_steps(row, *, meta_patch: dict[str, Any] | None = None) -> bool:
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    state = dict(_campaign_state(refreshed))
    if not state.get("enabled"):
        return False

    patch = dict(meta_patch or {})
    if refreshed.auto_promotion:
        pdd_ids = list(state.get("batch_pdd_ids") or refreshed.pdd_product_ids or [])
        mapping_ids = list(state.get("batch_mapping_ids") or refreshed.mapping_ids or [])
        if pdd_ids or mapping_ids:
            _enqueue_traffic_for_batch(
                refreshed,
                pdd_ids=pdd_ids,
                mapping_ids=mapping_ids,
                meta_patch=patch,
            )
            return True

    if state.get("is_final_batch"):
        _complete_per_batch_pipeline(refreshed, meta_patch=patch)
        return True
    return _schedule_next_listing_batch(refreshed, state)


def maybe_run_per_batch_campaign_after_listing(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_meta: dict[str, Any] | None = None,
) -> bool:
    """上架批次完成后调用（未启用「每批限时限量购」时）。"""
    if is_per_batch_limited_time_enabled(row) and _pipeline_auto_limited_time(row):
        return False
    if not _should_handle(row):
        return False

    meta_patch, more_batches, batch_index = _merge_listing_meta(
        row,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        listing_meta=listing_meta,
    )
    return _start_batch_campaign_chain(
        row,
        pdd_ids=list(pdd_ids),
        mapping_ids=list(mapping_ids),
        meta_patch=meta_patch,
    )


def maybe_start_per_batch_campaign_after_limited_time(
    row,
    *,
    run_id: str,
    success: bool,
    error: str = "",
) -> bool:
    """限时限量购完成后调用，启动本批活动 / 推广链。"""
    if not _should_handle(row):
        return False
    if not is_per_batch_limited_time_enabled(row):
        return False

    current_lt_run_id = str((row.meta or {}).get("limited_time_run_id") or "").strip()
    if current_lt_run_id != str(run_id or "").strip():
        return False

    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        filter_products_for_per_batch_campaign_after_limited_time,
        is_activity_limited_time_success_only_row,
    )

    pdd_ids = list(row.pdd_product_ids or [])
    mapping_ids = list(row.mapping_ids or [])
    if is_activity_limited_time_success_only_row(row):
        pdd_ids, mapping_ids, should_continue, block_reason = (
            filter_products_for_per_batch_campaign_after_limited_time(
                row,
                run_id=run_id,
                success=success,
                error=error,
                pdd_ids=pdd_ids,
                mapping_ids=mapping_ids,
            )
        )
        if not should_continue:
            update_integrated_pipeline(
                row.pipeline_id,
                status="failed",
                current_step="limited_time_failed",
                error=block_reason or error or "限时限量购无成功商品",
            )
            return True
        from pdd_agent.api.services.pipeline_activity_limited_time_success import (
            LimitedTimeSuccessProducts,
            build_limited_time_success_meta_patch,
        )

        update_integrated_pipeline(
            row.pipeline_id,
            pdd_product_ids=pdd_ids,
            mapping_ids=mapping_ids,
            meta_patch=build_limited_time_success_meta_patch(
                LimitedTimeSuccessProducts(
                    pdd_product_ids=pdd_ids,
                    mapping_ids=mapping_ids,
                    source="limited_time_success",
                    detail=block_reason,
                )
            ),
        )
        row = get_integrated_pipeline(row.pipeline_id) or row
    elif not success and not _pipeline_continue_after_limited_time_failure(row):
        return False

    lt_state = dict((row.meta or {}).get("listing_per_batch_limited_time") or {})
    if not lt_state.get("enabled"):
        return False

    state = _campaign_state(row)
    if state.get("enabled") and state.get("phase") in {"campaign", "traffic"}:
        return False

    throttle = _throttle_state(row)
    batch_index = int(throttle.get("batch_index") or 0)
    pending = dict(lt_state.get("pending") or {})
    more_batches = bool(pending)
    interval_minutes = max(1, int(throttle.get("interval_minutes") or 1))

    campaign_state = _build_batch_followup_state(
        batch_index=batch_index,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        more_batches=more_batches,
        interval_minutes=interval_minutes,
    )
    if pending:
        campaign_state["pending_listing"] = pending
    campaign_state["is_final_batch"] = bool(lt_state.get("awaiting_final_activity"))

    return _start_batch_campaign_chain(
        row,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        meta_patch={META_STATE_KEY: campaign_state},
    )


def maybe_continue_after_per_batch_campaign(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> bool:
    """活动报名完成后调用。"""
    if not _should_handle(row):
        return False
    state = _campaign_state(row)
    if not state.get("enabled") or state.get("phase") != "campaign":
        return False
    if str(row.campaign_run_id or "").strip() != str(run_id or "").strip():
        return False

    result = result if isinstance(result, dict) else {}
    activity_ids = _pipeline_activity_ids(row)
    activity_index = int(state.get("activity_index") or 0)
    current_activity_id = (
        activity_ids[activity_index] if activity_index < len(activity_ids) else str(row.activity_id or "")
    )
    activity_skipped = (not success) and _should_skip_campaign_for_traffic(result, error)
    activity_continue = (
        (not success) and not activity_skipped and _pipeline_continue_after_activity_failure(row)
    )

    if not success and not activity_skipped and not activity_continue:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="activity_failed",
            error=error or "活动报名失败",
            meta_patch={
                META_STATE_KEY: {**state, "phase": "failed"},
            },
        )
        return True

    next_index = activity_index + 1
    meta_patch: dict[str, Any] = {
        META_STATE_KEY: {
            **state,
            "activity_index": next_index,
        }
    }
    pdd_ids = list(state.get("batch_pdd_ids") or row.pdd_product_ids or [])
    mapping_ids = list(state.get("batch_mapping_ids") or row.mapping_ids or [])

    if next_index < len(activity_ids):
        _enqueue_campaign_for_batch(
            row,
            activity_index=next_index,
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
            meta_patch=meta_patch,
        )
        logger.info(
            "pipeline %s per-batch next activity %s (%s/%s)",
            row.pipeline_id,
            activity_ids[next_index],
            next_index + 1,
            len(activity_ids),
        )
        return True

    logger.info(
        "pipeline %s per-batch activities done for batch=%s activity=%s skipped=%s",
        row.pipeline_id,
        int(state.get("batch_index") or 0) + 1,
        current_activity_id,
        activity_skipped,
    )
    return _advance_after_batch_steps(row, meta_patch=meta_patch)


def maybe_continue_after_per_batch_traffic(
    row,
    *,
    run_id: str,
    success: bool,
    error: str = "",
) -> bool:
    """推广完成后调用。"""
    if not _should_handle(row):
        return False
    state = _campaign_state(row)
    if not state.get("enabled") or state.get("phase") != "traffic":
        return False
    if str(row.traffic_run_id or "").strip() != str(run_id or "").strip():
        return False

    if not success:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="traffic_failed",
            error=error or "推广创建失败",
            meta_patch={
                "traffic_finish_handled": True,
                META_STATE_KEY: {**state, "phase": "failed"},
            },
        )
        return True

    meta_patch: dict[str, Any] = {
        "traffic_finish_handled": True,
        META_STATE_KEY: {**state, "phase": "done"},
    }
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    if state.get("is_final_batch"):
        _complete_per_batch_pipeline(refreshed, meta_patch=meta_patch)
        return True
    if _schedule_next_listing_batch(refreshed, state):
        update_integrated_pipeline(refreshed.pipeline_id, meta_patch=meta_patch)
        return True
    _complete_per_batch_pipeline(refreshed, meta_patch=meta_patch)
    return True

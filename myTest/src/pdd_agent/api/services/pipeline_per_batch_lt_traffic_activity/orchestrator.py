"""
分批整合链路编排：上架 → 限时限量购 → 推广 → 活动。

仅当同时开启「分批上架 + 每批限时限量购 + 本模式」时生效；
与 listing_per_batch_campaign（活动→推广）互斥。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
    record_activity_for_pipeline,
    record_limited_time_batch,
    record_listing_batch_from_result,
    record_promotion_batch,
)
from pdd_agent.api.services.pipeline_listing_throttle import (
    enqueue_listing_batch_for_pipeline,
)
from pdd_agent.api.services.pipeline_per_batch_limited_time import (
    is_per_batch_limited_time_continue_handled,
    mark_per_batch_limited_time_continue_handled,
)
from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.constants import (
    ACCUMULATED_LT_MAPPING_IDS_KEY,
    ACCUMULATED_LT_PDD_IDS_KEY,
    META_ENABLED_KEY,
    META_PROMOTE_LT_SUCCESS_ONLY_KEY,
    META_STATE_KEY,
    PHASE_CAMPAIGN,
    PHASE_DONE,
    PHASE_TRAFFIC,
)
from pdd_agent.api.services.task_runner import create_campaign_run, create_traffic_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import enqueue_task, get_integrated_pipeline, update_integrated_pipeline
from pdd_agent.domain.enums import AgentKind

logger = get_logger(__name__)


def per_batch_lt_traffic_activity_meta_patch(*, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {}
    return {META_ENABLED_KEY: True}


def per_batch_promote_lt_success_only_meta_patch(*, enabled: bool) -> dict[str, Any]:
    return {META_PROMOTE_LT_SUCCESS_ONLY_KEY: bool(enabled)}


def _promote_lt_success_only(row) -> bool:
    meta = dict(row.meta or {})
    if META_PROMOTE_LT_SUCCESS_ONLY_KEY in meta:
        return bool(meta.get(META_PROMOTE_LT_SUCCESS_ONLY_KEY))
    return True


def _throttle_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get("listing_throttle") or {})


def _lt_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get("listing_per_batch_limited_time") or {})


def _flow_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get(META_STATE_KEY) or {})


def _pipeline_activity_ids(row) -> list[str]:
    meta = dict(row.meta or {})
    ids = [str(item).strip() for item in (meta.get("activity_ids") or []) if str(item).strip()]
    if ids:
        return list(dict.fromkeys(ids))
    legacy = str(row.activity_id or "").strip()
    return [legacy] if legacy else []


def _should_handle(row) -> bool:
    meta = dict(row.meta or {})
    if not meta.get(META_ENABLED_KEY):
        return False
    if not meta.get("listing_per_batch_limited_time_enabled"):
        return False
    if meta.get("listing_per_batch_campaign_enabled"):
        return False
    throttle = _throttle_state(row)
    if not throttle.get("enabled"):
        return False
    return int(throttle.get("total_batches") or 0) > 1


def is_per_batch_lt_traffic_activity_enabled(row) -> bool:
    return _should_handle(row)


def _continue_after_activity_failure(row) -> bool:
    return bool((row.meta or {}).get("continue_after_activity_failure"))


def _auto_promotion(row) -> bool:
    return bool(getattr(row, "auto_promotion", False))


def _should_skip_campaign(result: dict[str, Any] | None, error: str) -> bool:
    from pdd_agent.api.services.pipeline_service import _should_skip_campaign_for_traffic

    return _should_skip_campaign_for_traffic(result, error)


def _resolve_lt_success_products(
    row,
    *,
    run_id: str,
    result: dict[str, Any] | None,
    batch_pdd_ids: list[str],
    batch_mapping_ids: list[str],
) -> tuple[list[str], list[str]]:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        extract_limited_time_success_products,
        load_limited_time_run_result,
    )

    payload = result if isinstance(result, dict) else load_limited_time_run_result(run_id)
    extract = extract_limited_time_success_products(
        payload,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=list(batch_pdd_ids),
        fallback_mapping_ids=list(batch_mapping_ids),
    )
    return list(extract.pdd_product_ids), list(extract.mapping_ids)


def _merge_unique_ids(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            pid = str(item or "").strip()
            if pid and pid not in seen:
                seen.add(pid)
                merged.append(pid)
    return merged


def _accumulated_lt_success_from_meta(meta: dict[str, Any]) -> tuple[list[str], list[str]]:
    pdd_ids = _merge_unique_ids(list(meta.get(ACCUMULATED_LT_PDD_IDS_KEY) or []))
    mapping_ids = _merge_unique_ids(list(meta.get(ACCUMULATED_LT_MAPPING_IDS_KEY) or []))
    return pdd_ids, mapping_ids


def _accumulate_lt_success_meta_patch(
    meta: dict[str, Any],
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
) -> dict[str, Any]:
    prev_pdd, prev_map = _accumulated_lt_success_from_meta(meta)
    merged_pdd = _merge_unique_ids(prev_pdd, list(pdd_ids))
    merged_map = _merge_unique_ids(prev_map, list(mapping_ids))
    return {
        ACCUMULATED_LT_PDD_IDS_KEY: merged_pdd,
        ACCUMULATED_LT_MAPPING_IDS_KEY: merged_map,
    }


def _resolve_all_lt_success_for_activity(row) -> tuple[list[str], list[str]]:
    """全部批次结束后：仅使用跨批累计的限时限量购成功商品报活动。"""
    meta = dict(row.meta or {})
    accumulated_pdd, accumulated_map = _accumulated_lt_success_from_meta(meta)
    if accumulated_pdd:
        from pdd_agent.api.services.pipeline_activity_limited_time_success import (
            resolve_mapping_ids_for_pdd_products,
        )

        mapping_ids = resolve_mapping_ids_for_pdd_products(
            str(row.account_id or ""),
            accumulated_pdd,
            fallback_mapping_ids=accumulated_map,
        )
        return accumulated_pdd, mapping_ids
    return [], []


def _resolve_activity_products(row) -> tuple[list[str], list[str]]:
    return _resolve_all_lt_success_for_activity(row)


def _build_flow_state(
    *,
    batch_index: int,
    batch_pdd_ids: list[str],
    batch_mapping_ids: list[str],
    is_final_batch: bool,
    pending_listing: dict[str, Any] | None,
    lt_success_pdd_ids: list[str],
    lt_success_mapping_ids: list[str],
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "enabled": True,
        "batch_index": batch_index,
        "batch_pdd_ids": list(batch_pdd_ids),
        "batch_mapping_ids": list(batch_mapping_ids),
        "lt_success_pdd_ids": list(lt_success_pdd_ids),
        "lt_success_mapping_ids": list(lt_success_mapping_ids),
        "activity_index": 0,
        "phase": PHASE_TRAFFIC,
        "is_final_batch": bool(is_final_batch),
    }
    if pending_listing:
        state["pending_listing"] = dict(pending_listing)
    return state


def _enqueue_traffic(
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
    flow = dict(patch.get(META_STATE_KEY) or _flow_state(row))
    flow["phase"] = PHASE_TRAFFIC
    patch[META_STATE_KEY] = flow
    patch["traffic_enqueued"] = True
    patch.pop("traffic_finish_handled", None)
    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="traffic_queued_per_batch_ltta",
        traffic_run_id=traffic_run_id,
        error="",
        meta_patch=patch,
    )
    return traffic_run_id


def _enqueue_campaign(
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
    flow = dict(patch.get(META_STATE_KEY) or _flow_state(row))
    flow["phase"] = PHASE_CAMPAIGN
    flow["activity_index"] = activity_index
    patch[META_STATE_KEY] = flow
    patch["campaign_activity_index"] = activity_index
    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="campaign_queued_per_batch_ltta",
        pdd_product_ids=list(pdd_ids),
        mapping_ids=list(mapping_ids),
        campaign_run_id=campaign_run_id,
        error="",
        meta_patch=patch,
    )
    return campaign_run_id


def _schedule_next_listing_batch(row, *, state: dict[str, Any], run_id: str = "") -> bool:
    pending = dict(state.get("pending_listing") or {})
    if not pending:
        return False

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    throttle = _throttle_state(refreshed)
    batches = list(throttle.get("batches") or [])
    next_index = int(pending.get("next_batch_index") or 0)
    if next_index < 0 or next_index >= len(batches):
        logger.warning(
            "pipeline %s ltta pending batch index out of range: %s",
            row.pipeline_id,
            next_index,
        )
        return False

    interval_minutes = max(
        1,
        int(
            pending.get("interval_minutes")
            or throttle.get("interval_minutes")
            or 1
        ),
    )
    scheduled_at = datetime.now() + timedelta(minutes=interval_minutes)
    payload_base = dict(throttle.get("listing_payload_base") or {})
    flow = dict(_flow_state(refreshed))
    flow["pending_listing"] = None
    flow["phase"] = PHASE_DONE
    update_integrated_pipeline(
        refreshed.pipeline_id,
        current_step=f"waiting_listing_batch_{next_index + 1}",
        meta_patch={
            META_STATE_KEY: flow,
            "listing_throttle": {**throttle, "batch_index": next_index},
        },
    )
    enqueue_listing_batch_for_pipeline(
        pipeline_id=refreshed.pipeline_id,
        account_id=refreshed.account_id,
        batch_codes=list(batches[next_index]),
        listing_payload_base=payload_base,
        scheduled_at=scheduled_at,
    )
    if run_id:
        mark_per_batch_limited_time_continue_handled(refreshed, run_id)
    logger.info(
        "pipeline %s ltta scheduled next listing batch %s/%s at %s",
        refreshed.pipeline_id,
        next_index + 1,
        len(batches),
        scheduled_at,
    )
    return True


def _complete_pipeline(row, *, meta_patch: dict[str, Any] | None = None) -> None:
    patch = dict(meta_patch or {})
    flow = dict(_flow_state(row))
    flow["phase"] = PHASE_DONE
    patch[META_STATE_KEY] = flow
    update_integrated_pipeline(
        row.pipeline_id,
        status="completed",
        current_step="completed",
        error="",
        meta_patch=patch,
    )
    logger.info("pipeline %s ltta flow completed", row.pipeline_id)


def _start_final_activities(row, *, meta_patch: dict[str, Any] | None = None) -> bool:
    activity_ids = _pipeline_activity_ids(row)
    if not activity_ids:
        _complete_pipeline(row, meta_patch=meta_patch)
        return True
    pdd_ids, mapping_ids = _resolve_all_lt_success_for_activity(row)
    if not pdd_ids:
        patch = dict(meta_patch or {})
        patch["campaign_skip_reason"] = "全部批次无限时限量购成功商品，跳过活动报名"
        patch["campaign_outcome"] = "skipped_no_lt_success"
        _complete_pipeline(row, meta_patch=patch)
        return True
    patch = dict(meta_patch or {})
    flow = _build_flow_state(
        batch_index=int(_flow_state(row).get("batch_index") or _throttle_state(row).get("batch_index") or 0),
        batch_pdd_ids=pdd_ids,
        batch_mapping_ids=mapping_ids,
        is_final_batch=True,
        pending_listing=None,
        lt_success_pdd_ids=pdd_ids,
        lt_success_mapping_ids=mapping_ids,
    )
    flow["phase"] = PHASE_CAMPAIGN
    flow["activity_index"] = 0
    patch[META_STATE_KEY] = flow
    _enqueue_campaign(
        row,
        activity_index=0,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        meta_patch=patch,
    )
    logger.info(
        "pipeline %s ltta all-batch activities started pdd_ids=%s activities=%s",
        row.pipeline_id,
        pdd_ids,
        activity_ids,
    )
    return True


def record_listing_batch(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_result: dict[str, Any] | None,
) -> None:
    if not _should_handle(row):
        return
    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
        resolve_finished_listing_batch_index,
    )

    batch_index = resolve_finished_listing_batch_index(row)
    throttle = _throttle_state(row)
    batches = list(throttle.get("batches") or [])
    selectors = list(batches[batch_index]) if 0 <= batch_index < len(batches) else []
    record_listing_batch_from_result(
        pipeline_id=row.pipeline_id,
        account_id=str(row.account_id or ""),
        batch_index=batch_index,
        batch_selectors=selectors,
        listing_result=listing_result,
        activity_ids=_pipeline_activity_ids(row),
    )


def handle_limited_time_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    if not _should_handle(row):
        return False

    current_lt_run_id = str((row.meta or {}).get("limited_time_run_id") or "").strip()
    if current_lt_run_id != str(run_id or "").strip():
        return False

    flow = _flow_state(row)
    if flow.get("enabled") and flow.get("phase") in {PHASE_TRAFFIC, PHASE_CAMPAIGN}:
        return False

    lt_state = _lt_state(row)
    if not lt_state.get("enabled"):
        return False

    throttle = _throttle_state(row)
    batch_index = int(lt_state.get("last_batch_index") if lt_state.get("last_batch_index") is not None else throttle.get("batch_index") or 0)
    batch_pdd_ids = list(row.pdd_product_ids or [])
    batch_mapping_ids = list(row.mapping_ids or [])
    is_final_batch = bool(lt_state.get("awaiting_final_activity"))
    pending_listing = dict(lt_state.get("pending") or {}) or None

    lt_success_pdd_ids, lt_success_mapping_ids = _resolve_lt_success_products(
        row,
        run_id=run_id,
        result=result,
        batch_pdd_ids=batch_pdd_ids,
        batch_mapping_ids=batch_mapping_ids,
    )

    failed_pdd = [pid for pid in batch_pdd_ids if pid not in set(lt_success_pdd_ids)]
    record_limited_time_batch(
        pipeline_id=row.pipeline_id,
        batch_index=batch_index,
        success_pdd_ids=lt_success_pdd_ids,
        failed_pdd_ids=failed_pdd,
        batch_failed=not success and not lt_success_pdd_ids,
        error=error or "限时限量购设置失败",
    )

    meta_patch: dict[str, Any] = {
        "limited_time_finish_handled": True,
        "limited_time_outcome": "success" if (success or lt_success_pdd_ids) else "failed",
    }
    if not success and not lt_success_pdd_ids:
        meta_patch["limited_time_skip_reason"] = error or "限时限量购设置失败"
    meta_patch.update(
        _accumulate_lt_success_meta_patch(
            dict(row.meta or {}),
            pdd_ids=lt_success_pdd_ids,
            mapping_ids=lt_success_mapping_ids,
        )
    )

    flow_state = _build_flow_state(
        batch_index=batch_index,
        batch_pdd_ids=batch_pdd_ids,
        batch_mapping_ids=batch_mapping_ids,
        is_final_batch=is_final_batch,
        pending_listing=pending_listing,
        lt_success_pdd_ids=lt_success_pdd_ids,
        lt_success_mapping_ids=lt_success_mapping_ids,
    )
    meta_patch[META_STATE_KEY] = flow_state

    promote_lt_success_only = _promote_lt_success_only(row)
    if promote_lt_success_only:
        promote_pdd_ids = list(lt_success_pdd_ids)
        promote_mapping_ids = list(lt_success_mapping_ids)
        skip_promotion_error = error or "本批无限时限量购成功商品，跳过推广"
    else:
        promote_pdd_ids = list(batch_pdd_ids)
        promote_mapping_ids = list(batch_mapping_ids)
        skip_promotion_error = "本批无上架成功商品，跳过推广"

    flow_state["lt_success_pdd_ids"] = promote_pdd_ids
    flow_state["lt_success_mapping_ids"] = promote_mapping_ids
    flow_state["promote_lt_success_only"] = promote_lt_success_only
    meta_patch[META_STATE_KEY] = flow_state

    # 无推广目标：跳过推广，不中断，继续下一批或全部结束后报活动
    if not promote_pdd_ids:
        record_promotion_batch(
            pipeline_id=row.pipeline_id,
            batch_index=batch_index,
            target_pdd_ids=[],
            success=False,
            skipped=True,
            error=skip_promotion_error,
        )
        update_integrated_pipeline(
            row.pipeline_id,
            status="running",
            current_step="waiting_limited_time_per_batch" if not is_final_batch else "limited_time_failed_continue_ltta",
            error="",
            meta_patch=meta_patch,
        )
        if is_final_batch:
            return _start_final_activities(get_integrated_pipeline(row.pipeline_id) or row, meta_patch=meta_patch)
        return _schedule_next_listing_batch(row, state=flow_state, run_id=run_id)

    # 有推广目标且开启自动推广
    if _auto_promotion(row):
        update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)
        _enqueue_traffic(
            get_integrated_pipeline(row.pipeline_id) or row,
            pdd_ids=promote_pdd_ids,
            mapping_ids=promote_mapping_ids,
            meta_patch=meta_patch,
        )
        logger.info(
            "pipeline %s ltta traffic queued batch=%s final=%s lt_success_only=%s pdd_ids=%s",
            row.pipeline_id,
            batch_index + 1,
            is_final_batch,
            promote_lt_success_only,
            promote_pdd_ids,
        )
        return True

    record_promotion_batch(
        pipeline_id=row.pipeline_id,
        batch_index=batch_index,
        target_pdd_ids=promote_pdd_ids,
        success=False,
        skipped=True,
        error="未启用自动推广",
    )
    if is_final_batch:
        update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)
        return _start_final_activities(get_integrated_pipeline(row.pipeline_id) or row, meta_patch=meta_patch)

    update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)
    return _schedule_next_listing_batch(row, state=flow_state, run_id=run_id)


def handle_traffic_finished(
    row,
    *,
    run_id: str,
    success: bool,
    error: str,
    result: dict[str, Any] | None = None,
) -> bool:
    if not _should_handle(row):
        return False
    state = _flow_state(row)
    if not state.get("enabled") or state.get("phase") != PHASE_TRAFFIC:
        return False
    if str(row.traffic_run_id or "").strip() != str(run_id or "").strip():
        return False

    batch_index = int(state.get("batch_index") or 0)
    target_pdd_ids = list(state.get("lt_success_pdd_ids") or [])
    record_promotion_batch(
        pipeline_id=row.pipeline_id,
        batch_index=batch_index,
        target_pdd_ids=target_pdd_ids,
        success=bool(success),
        skipped=not target_pdd_ids,
        error=error or "推广创建失败",
    )

    meta_patch: dict[str, Any] = {
        "traffic_finish_handled": True,
        META_STATE_KEY: {**state, "phase": PHASE_DONE},
    }
    refreshed = get_integrated_pipeline(row.pipeline_id) or row

    if state.get("is_final_batch"):
        update_integrated_pipeline(refreshed.pipeline_id, meta_patch=meta_patch)
        return _start_final_activities(get_integrated_pipeline(refreshed.pipeline_id) or refreshed, meta_patch=meta_patch)

    update_integrated_pipeline(refreshed.pipeline_id, meta_patch=meta_patch)
    return _schedule_next_listing_batch(refreshed, state=state, run_id=str((row.meta or {}).get("limited_time_run_id") or ""))


def handle_campaign_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    if not _should_handle(row):
        return False
    state = _flow_state(row)
    if not state.get("enabled") or state.get("phase") != PHASE_CAMPAIGN:
        return False
    if str(row.campaign_run_id or "").strip() != str(run_id or "").strip():
        return False
    if not state.get("is_final_batch"):
        return False

    result = result if isinstance(result, dict) else {}
    activity_ids = _pipeline_activity_ids(row)
    activity_index = int(state.get("activity_index") or 0)
    current_activity_id = (
        activity_ids[activity_index] if activity_index < len(activity_ids) else str(row.activity_id or "")
    )
    activity_skipped = (not success) and _should_skip_campaign(result, error)
    activity_continue = (not success) and not activity_skipped and _continue_after_activity_failure(row)

    pdd_ids, _mapping_ids = _resolve_all_lt_success_for_activity(row)
    record_activity_for_pipeline(
        pipeline_id=row.pipeline_id,
        activity_index=activity_index,
        activity_id=current_activity_id,
        target_pdd_ids=pdd_ids,
        success=bool(success),
        skipped=activity_skipped,
        error=error or "活动报名失败",
    )

    if not success and not activity_skipped and not activity_continue:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="activity_failed",
            error=error or "活动报名失败",
            meta_patch={META_STATE_KEY: {**state, "phase": "failed"}},
        )
        return True

    next_index = activity_index + 1
    meta_patch: dict[str, Any] = {META_STATE_KEY: {**state, "activity_index": next_index}}

    if next_index < len(activity_ids):
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        pdd_ids, mapping_ids = _resolve_all_lt_success_for_activity(refreshed)
        _enqueue_campaign(
            refreshed,
            activity_index=next_index,
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
            meta_patch=meta_patch,
        )
        logger.info(
            "pipeline %s ltta next activity %s (%s/%s)",
            row.pipeline_id,
            activity_ids[next_index],
            next_index + 1,
            len(activity_ids),
        )
        return True

    _complete_pipeline(get_integrated_pipeline(row.pipeline_id) or row, meta_patch=meta_patch)
    return True


def should_absorb_task_failure(row, *, agent: str, run_id: str, success: bool) -> bool:
    """推广失败不阻断链路（由 orchestrator 继续后续步骤）。"""
    if success or not _should_handle(row):
        return False
    if agent != AgentKind.TRAFFIC.value:
        return False
    state = _flow_state(row)
    if not state.get("enabled"):
        return False
    if str(row.traffic_run_id or "").strip() != str(run_id or "").strip():
        return False
    return state.get("phase") == PHASE_TRAFFIC

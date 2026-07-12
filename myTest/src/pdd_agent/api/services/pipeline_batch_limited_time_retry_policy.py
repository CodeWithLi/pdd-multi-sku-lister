"""
整合链路 — 分批「上架成功 + 限时限量购失败」重跑。

仅在标准分批限时聚合模式（非每批限时→推广→活动）下生效：
  - 全部批次跑完后，可按 batch_index 重跑限时失败商品（跳过上架）；
  - 至少一批重跑有成功 → 活动池追加商品，并按最后成功批次的限时完成时刻 + delay 预约/改期；
  - 全部限时失败导致链路 failed 时，重跑成功可恢复为 waiting_activity。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.api.services.task_runner import create_campaign_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import enqueue_task, get_integrated_pipeline, update_integrated_pipeline
from pdd_agent.domain.enums import AgentKind
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)

META_STATE_KEY = "pipeline_batch_limited_time_retry"
POLICY_META_FLAG = "pipeline_batch_limited_time_retry_enabled"

PHASE_IDLE = "idle"
PHASE_LIMITED_TIME = "limited_time"
PHASE_DONE = "done"
PHASE_PARTIAL = "partial_done"

ACTIVE_PHASES = frozenset({PHASE_LIMITED_TIME})


def _meta(row) -> dict[str, Any]:
    raw = getattr(row, "meta", None) if row is not None else None
    return dict(raw) if isinstance(raw, dict) else {}


def batch_lt_retry_state(row) -> dict[str, Any]:
    state = _meta(row).get(META_STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _save_batch_lt_retry_state(row, patch: dict[str, Any]) -> None:
    current = dict(batch_lt_retry_state(row))
    current.update(patch)
    update_integrated_pipeline(row.pipeline_id, meta_patch={META_STATE_KEY: current})


def _merge_unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def is_standard_per_batch_lt_aggregate_pipeline(row) -> bool:
    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        is_standard_per_batch_lt_pipeline,
    )

    return bool(is_standard_per_batch_lt_pipeline(row))


def is_pipeline_all_batches_complete(row) -> bool:
    """兼容旧名：分批限时重跑仅要求全部分批上架完成。"""
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_eligibility import (
        is_pipeline_listing_batches_complete,
    )

    return is_pipeline_listing_batches_complete(row)


def list_batch_limited_time_retry_targets(
    *,
    pipeline_id: str,
    batch_index: int,
) -> list[dict[str, Any]]:
    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
        STAGE_FAILED,
        STAGE_SUCCESS,
        list_pipeline_batch_product_stages,
    )

    items = list_pipeline_batch_product_stages(pipeline_id=pipeline_id, batch_index=int(batch_index))
    targets: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("listing_status") or "") != STAGE_SUCCESS:
            continue
        if str(item.get("limited_time_status") or "") != STAGE_FAILED:
            continue
        pid = str(item.get("pdd_product_id") or "").strip()
        if not pid:
            continue
        targets.append(item)
    return targets


def evaluate_batch_limited_time_retry_eligibility(row, batch_index: int) -> dict[str, Any]:
    if row is None:
        return {"eligible": False, "reason": "pipeline_not_found", "batch_index": batch_index}
    if not is_standard_per_batch_lt_aggregate_pipeline(row):
        return {"eligible": False, "reason": "not_standard_per_batch_lt_pipeline", "batch_index": batch_index}

    from pdd_agent.api.services.pipeline_batch_limited_time_retry_eligibility import (
        is_batch_initial_limited_time_recorded,
        is_pipeline_listing_batches_complete,
    )

    if not is_pipeline_listing_batches_complete(row):
        return {"eligible": False, "reason": "listing_batches_not_complete", "batch_index": batch_index}

    from pdd_agent.api.services.pipeline_late_retry_policy import late_retry_state, ACTIVE_PHASES as LATE_ACTIVE

    late_state = late_retry_state(row)
    if str(late_state.get("phase") or "") in LATE_ACTIVE:
        return {"eligible": False, "reason": "late_retry_in_progress", "batch_index": batch_index}

    state = batch_lt_retry_state(row)
    phase = str(state.get("phase") or PHASE_IDLE)
    pending = [int(x) for x in (state.get("pending_batch_indices") or [])]
    active_batch = state.get("active_batch_index")
    if phase in ACTIVE_PHASES:
        if int(batch_index) == int(active_batch or -1):
            return {"eligible": False, "reason": "batch_retry_in_progress", "batch_index": batch_index}
        if int(batch_index) in pending:
            return {"eligible": False, "reason": "batch_retry_already_queued", "batch_index": batch_index}

    targets = list_batch_limited_time_retry_targets(
        pipeline_id=row.pipeline_id,
        batch_index=int(batch_index),
    )
    if not targets:
        return {
            "eligible": False,
            "reason": "no_limited_time_retry_targets",
            "batch_index": batch_index,
            "retry_count": 0,
            "pdd_product_ids": [],
        }

    if not is_batch_initial_limited_time_recorded(targets):
        return {
            "eligible": False,
            "reason": "batch_initial_limited_time_not_finished",
            "batch_index": batch_index,
            "retry_count": 0,
            "pdd_product_ids": [],
        }

    pdd_ids = _merge_unique([str(item.get("pdd_product_id") or "") for item in targets])
    return {
        "eligible": True,
        "reason": "",
        "batch_index": int(batch_index),
        "retry_count": len(targets),
        "pdd_product_ids": pdd_ids,
    }


def build_batch_limited_time_retry_public_state(row) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
        build_batch_lt_retry_activity_defer_public_state,
    )

    state = batch_lt_retry_state(row)
    return {
        "enabled": bool(state.get(POLICY_META_FLAG) or state.get("enabled")),
        "phase": str(state.get("phase") or PHASE_IDLE),
        "outcome": str(state.get("outcome") or ""),
        "outcome_detail": str(state.get("outcome_detail") or ""),
        "active_batch_index": state.get("active_batch_index"),
        "pending_batch_indices": list(state.get("pending_batch_indices") or []),
        "completed_batch_indices": list(state.get("completed_batch_indices") or []),
        "limited_time_run_id": str(state.get("limited_time_run_id") or ""),
        "last_success_finished_at": str(state.get("last_success_finished_at") or ""),
        "merged_pdd_count": int(state.get("merged_pdd_count") or 0),
        "activity_defer": build_batch_lt_retry_activity_defer_public_state(row),
    }


def _extract_targets_pdd_mapping(targets: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    pdd_ids = _merge_unique([str(item.get("pdd_product_id") or "") for item in targets])
    mapping_ids = _merge_unique([str(item.get("mapping_id") or "") for item in targets])
    return pdd_ids, mapping_ids


def _enqueue_batch_limited_time_retry(
    row,
    *,
    batch_index: int,
    pdd_ids: list[str],
    mapping_ids: list[str],
) -> str:
    from pdd_agent.api.services.pipeline_per_batch_lt_chunks.bridge import (
        maybe_start_chunked_batch_limited_time_retry,
    )

    chunked_run_id = maybe_start_chunked_batch_limited_time_retry(
        row,
        batch_index=int(batch_index),
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    )
    if chunked_run_id:
        return chunked_run_id

    limited_time_run_id = create_campaign_run(str(row.account_id or ""))
    enqueue_task(
        agent=AgentKind.CAMPAIGN.value,
        run_id=limited_time_run_id,
        account_id=str(row.account_id or ""),
        payload={
            "pipeline_id": row.pipeline_id,
            "campaign_type": "limited_time_setup",
            "pdd_product_ids": list(pdd_ids),
            "published_mapping_ids": list(mapping_ids),
            "pipeline_batch_limited_time_retry": True,
            "pipeline_batch_limited_time_retry_batch_index": int(batch_index),
        },
        scheduled_at=datetime.now() + timedelta(seconds=5),
    )
    _save_batch_lt_retry_state(
        row,
        {
            POLICY_META_FLAG: True,
            "enabled": True,
            "phase": PHASE_LIMITED_TIME,
            "active_batch_index": int(batch_index),
            "limited_time_run_id": limited_time_run_id,
            "started_at": datetime.now().isoformat(),
            "outcome": "",
            "outcome_detail": "",
        },
    )
    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="batch_limited_time_retry",
        error="",
    )
    logger.info(
        "pipeline %s batch lt retry queued batch=%s run_id=%s pdd_ids=%s",
        row.pipeline_id,
        batch_index + 1,
        limited_time_run_id,
        pdd_ids,
    )
    return limited_time_run_id


def start_batch_limited_time_retry(pipeline_id: str, *, batch_index: int) -> dict[str, Any]:
    pipeline_id = str(pipeline_id or "").strip()
    row = get_integrated_pipeline(pipeline_id)
    if not row:
        raise ValueError("pipeline_not_found")

    eligibility = evaluate_batch_limited_time_retry_eligibility(row, int(batch_index))
    if not eligibility.get("eligible"):
        raise ValueError(str(eligibility.get("reason") or "not_eligible"))

    targets = list_batch_limited_time_retry_targets(pipeline_id=pipeline_id, batch_index=int(batch_index))
    pdd_ids, mapping_ids = _extract_targets_pdd_mapping(targets)
    if not pdd_ids:
        raise ValueError("no_limited_time_retry_targets")

    state = batch_lt_retry_state(row)
    phase = str(state.get("phase") or PHASE_IDLE)
    queued = False
    if phase == PHASE_IDLE:
        update_integrated_pipeline(
            pipeline_id,
            meta_patch={
                "batch_lt_retry_restore_step": str(getattr(row, "current_step", "") or ""),
                "batch_lt_retry_restore_status": str(getattr(row, "status", "") or ""),
            },
        )
    if phase in ACTIVE_PHASES:
        pending = [int(x) for x in (state.get("pending_batch_indices") or [])]
        if int(batch_index) not in pending:
            pending.append(int(batch_index))
        _save_batch_lt_retry_state(row, {"pending_batch_indices": pending})
        queued = True
        run_id = str(state.get("limited_time_run_id") or "")
    else:
        from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
            is_defer_policy_enabled,
        )

        if is_defer_policy_enabled(row):
            scheduled = getattr(row, "scheduled_activity_at", None)
            update_integrated_pipeline(
                pipeline_id,
                meta_patch={
                    "pipeline_batch_lt_retry_activity_defer": {
                        "original_activity_at": scheduled.isoformat() if isinstance(scheduled, datetime) else "",
                        "awaiting_reschedule": False,
                    }
                },
            )
        run_id = _enqueue_batch_limited_time_retry(
            row,
            batch_index=int(batch_index),
            pdd_ids=pdd_ids,
            mapping_ids=mapping_ids,
        )

    refreshed = get_integrated_pipeline(pipeline_id) or row
    return {
        "pipeline_id": pipeline_id,
        "batch_index": int(batch_index),
        "limited_time_run_id": run_id,
        "retry_count": len(targets),
        "pdd_product_ids": pdd_ids,
        "queued": queued,
        "batch_limited_time_retry": build_batch_limited_time_retry_public_state(refreshed),
    }


def is_batch_limited_time_retry_run(row, run_id: str) -> bool:
    rid = str(run_id or "").strip()
    if not rid:
        return False
    state = batch_lt_retry_state(row)
    if str(state.get("limited_time_run_id") or "").strip() == rid:
        return True
    return rid in {str(item or "").strip() for item in (state.get("historical_run_ids") or [])}


def _merge_limited_time_success_into_activity_pool(
    row,
    *,
    run_id: str,
    result: dict[str, Any] | None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        META_ACTIVITY_PDD_IDS_KEY,
        META_LT_SUCCESS_MAPPING_IDS_KEY,
        META_LT_SUCCESS_PDD_IDS_KEY,
        LimitedTimeSuccessProducts,
        build_limited_time_success_meta_patch,
        extract_limited_time_success_products,
    )
    from pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy import (
        ACCUMULATED_MAPPING_IDS_KEY,
        ACCUMULATED_PDD_IDS_KEY,
    )
    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.constants import (
        AGG_MAPPING_IDS_KEY,
        AGG_PDD_IDS_KEY,
    )

    meta = _meta(row)
    extract = extract_limited_time_success_products(
        result,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=[],
        fallback_mapping_ids=[],
    )

    existing_pdd = _merge_unique(
        list(meta.get(META_ACTIVITY_PDD_IDS_KEY) or [])
        + list(meta.get(META_LT_SUCCESS_PDD_IDS_KEY) or [])
        + list(meta.get(ACCUMULATED_PDD_IDS_KEY) or [])
        + list(meta.get(AGG_PDD_IDS_KEY) or [])
        + list(row.pdd_product_ids or [])
    )
    existing_map = _merge_unique(
        list(meta.get(META_LT_SUCCESS_MAPPING_IDS_KEY) or [])
        + list(meta.get(ACCUMULATED_MAPPING_IDS_KEY) or [])
        + list(meta.get(AGG_MAPPING_IDS_KEY) or [])
        + list(row.mapping_ids or [])
    )

    merged_pdd = _merge_unique([*existing_pdd, *extract.pdd_product_ids])
    merged_map = _merge_unique([*existing_map, *extract.mapping_ids])

    patch = build_limited_time_success_meta_patch(
        LimitedTimeSuccessProducts(
            pdd_product_ids=merged_pdd,
            mapping_ids=merged_map,
            source="batch_limited_time_retry_success",
            detail=(
                f"分批限时重跑成功 {len(extract.pdd_product_ids)} 个，"
                f"活动池合计 {len(merged_pdd)} 个"
            ),
        )
    )
    patch[ACCUMULATED_PDD_IDS_KEY] = merged_pdd
    patch[ACCUMULATED_MAPPING_IDS_KEY] = merged_map
    patch[AGG_PDD_IDS_KEY] = merged_pdd
    patch[AGG_MAPPING_IDS_KEY] = merged_map
    patch["batch_lt_retry_limited_time_run_id"] = str(run_id or "").strip()
    patch["batch_lt_retry_limited_time_detail"] = extract.detail

    update_integrated_pipeline(
        row.pipeline_id,
        pdd_product_ids=merged_pdd,
        mapping_ids=merged_map,
        meta_patch=patch,
    )
    return merged_pdd, merged_map, list(extract.pdd_product_ids), list(extract.mapping_ids or [])


def _resolve_lt_success_for_batch(
    row,
    *,
    run_id: str,
    result: dict[str, Any] | None,
    batch_pdd_ids: list[str],
    batch_mapping_ids: list[str],
) -> tuple[list[str], list[str], list[str]]:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        extract_limited_time_success_products,
        load_limited_time_run_result,
        resolve_mapping_ids_for_pdd_products,
    )

    payload = result if isinstance(result, dict) else load_limited_time_run_result(run_id)
    extract = extract_limited_time_success_products(
        payload,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=list(batch_pdd_ids),
        fallback_mapping_ids=list(batch_mapping_ids),
    )
    mapping_ids = resolve_mapping_ids_for_pdd_products(
        str(row.account_id or ""),
        extract.pdd_product_ids,
        fallback_mapping_ids=extract.mapping_ids,
    )
    success_set = set(extract.pdd_product_ids)
    failed_pdd = [pid for pid in batch_pdd_ids if pid not in success_set]
    return list(extract.pdd_product_ids), list(mapping_ids), failed_pdd


def _start_next_pending_batch(row) -> bool:
    state = batch_lt_retry_state(row)
    pending = [int(x) for x in (state.get("pending_batch_indices") or [])]
    if not pending:
        return False
    next_batch = pending.pop(0)
    targets = list_batch_limited_time_retry_targets(
        pipeline_id=row.pipeline_id,
        batch_index=next_batch,
    )
    if not targets:
        _save_batch_lt_retry_state(row, {"pending_batch_indices": pending})
        return _start_next_pending_batch(get_integrated_pipeline(row.pipeline_id) or row)
    pdd_ids, mapping_ids = _extract_targets_pdd_mapping(targets)
    _save_batch_lt_retry_state(row, {"pending_batch_indices": pending})
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    _enqueue_batch_limited_time_retry(
        refreshed,
        batch_index=next_batch,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    )
    return True


def maybe_handle_batch_limited_time_retry_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any],
    error: str,
) -> bool:
    if not is_batch_limited_time_retry_run(row, run_id):
        return False

    from pdd_agent.api.services.pipeline_per_batch_lt_chunks.bridge import (
        consume_chunk_retry_finish_context,
        is_limited_time_chunk_sequence_active,
        maybe_handle_limited_time_chunk_finished,
        merge_chunk_retry_success_into_activity_pool,
    )

    if is_limited_time_chunk_sequence_active(row):
        if maybe_handle_limited_time_chunk_finished(
            row,
            run_id=run_id,
            success=success,
            result=result,
            error=error,
        ):
            return True

    chunk_ctx = consume_chunk_retry_finish_context(row)
    result = result if isinstance(result, dict) else {}
    state = batch_lt_retry_state(row)
    batch_index = int(
        (chunk_ctx.get("batch_index") if chunk_ctx else None)
        or state.get("active_batch_index")
        or 0
    )
    targets = list_batch_limited_time_retry_targets(
        pipeline_id=row.pipeline_id,
        batch_index=batch_index,
    )
    batch_pdd_ids, batch_mapping_ids = _extract_targets_pdd_mapping(targets)

    if chunk_ctx:
        lt_success_pdd = list(chunk_ctx.get("chunk_success_pdd_ids") or [])
        lt_success_mapping = list(chunk_ctx.get("chunk_success_mapping_ids") or [])
        failed_pdd = [pid for pid in batch_pdd_ids if pid not in set(lt_success_pdd)]
        success = bool(lt_success_pdd) or bool(chunk_ctx.get("last_chunk_success"))
        if not str(error or "").strip():
            error = str(chunk_ctx.get("error") or "")
    else:
        lt_success_pdd, lt_success_mapping, failed_pdd = _resolve_lt_success_for_batch(
            row,
            run_id=run_id,
            result=result,
            batch_pdd_ids=batch_pdd_ids,
            batch_mapping_ids=batch_mapping_ids,
        )

        from pdd_agent.api.services.pipeline_batch_product_stage_tracker import record_limited_time_batch

        record_limited_time_batch(
            pipeline_id=row.pipeline_id,
            batch_index=batch_index,
            success_pdd_ids=lt_success_pdd,
            failed_pdd_ids=failed_pdd,
            batch_failed=not success and not lt_success_pdd,
            error=error or "限时限量购重跑失败",
        )

    merged_pdd: list[str] = []
    merged_map: list[str] = []
    if lt_success_pdd:
        if chunk_ctx:
            merged_pdd, merged_map, _, _ = merge_chunk_retry_success_into_activity_pool(
                row,
                lt_success_pdd=lt_success_pdd,
                lt_success_mapping=lt_success_mapping,
            )
        else:
            merged_pdd, merged_map, _, _ = _merge_limited_time_success_into_activity_pool(
                row,
                run_id=run_id,
                result=result,
            )
        from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
            record_batch_lt_retry_success_finished_at,
        )

        finished_at = datetime.now()
        record_batch_lt_retry_success_finished_at(row, finished_at=finished_at)
        _save_batch_lt_retry_state(
            row,
            {"last_success_finished_at": finished_at.isoformat()},
        )

    completed = list(state.get("completed_batch_indices") or [])
    if batch_index not in completed:
        completed.append(batch_index)
    historical = list(state.get("historical_run_ids") or [])
    historical.append(str(run_id or "").strip())

    outcome = "limited_time_merged" if lt_success_pdd else "limited_time_no_success"
    detail = f"第 {batch_index + 1} 批限时重跑成功 {len(lt_success_pdd)} 个" if lt_success_pdd else (
        error or "分批限时重跑无成功商品"
    )
    _save_batch_lt_retry_state(
        row,
        {
            "completed_batch_indices": completed,
            "historical_run_ids": historical,
            "limited_time_run_id": "",
            "active_batch_index": None,
            "merged_pdd_count": len(merged_pdd),
            "outcome": outcome,
            "outcome_detail": detail,
        },
    )

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    if _start_next_pending_batch(refreshed):
        logger.info(
            "pipeline %s batch lt retry batch=%s done, next pending batch started",
            row.pipeline_id,
            batch_index + 1,
        )
        return True

    from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
        maybe_finalize_activity_after_batch_lt_retry,
    )

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    finalized = maybe_finalize_activity_after_batch_lt_retry(refreshed)

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    if finalized:
        _save_batch_lt_retry_state(
            refreshed,
            {
                "phase": PHASE_DONE if not failed_pdd else PHASE_PARTIAL,
                "outcome": "activity_rescheduled",
                "outcome_detail": detail,
            },
        )
        update_integrated_pipeline(
            refreshed.pipeline_id,
            status="waiting_activity",
            current_step="waiting_activity",
            error="",
            meta_patch={
                "limited_time_outcome": "partial_success" if failed_pdd or not success else "success",
            },
        )
    else:
        phase = PHASE_PARTIAL if lt_success_pdd else PHASE_DONE
        _save_batch_lt_retry_state(
            refreshed,
            {
                "phase": phase,
                "outcome": outcome,
                "outcome_detail": detail,
            },
        )
        restore_step = str(_meta(refreshed).get("batch_lt_retry_restore_step") or "").strip()
        restore_status = str(_meta(refreshed).get("batch_lt_retry_restore_status") or "").strip()
        if not lt_success_pdd:
            if restore_status == "failed" or restore_step == "limited_time_failed":
                update_integrated_pipeline(
                    refreshed.pipeline_id,
                    status="failed",
                    current_step="limited_time_failed",
                    error=error or "限时限量购重跑无成功商品",
                )
            elif restore_step:
                update_integrated_pipeline(
                    refreshed.pipeline_id,
                    status=restore_status or "waiting_activity",
                    current_step=restore_step,
                    error="",
                )
            else:
                update_integrated_pipeline(
                    refreshed.pipeline_id,
                    current_step="waiting_activity",
                    error="",
                )
        else:
            from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
                build_activity_revive_meta_patch,
            )

            pending_reason = (
                "分批限时重跑已成功，活动将在首轮限时全部完成后按最后成功时刻改期预约"
                if not finalized
                else ""
            )
            update_integrated_pipeline(
                refreshed.pipeline_id,
                status="waiting_activity",
                current_step="waiting_activity",
                error="",
                traffic_run_id=None,
                meta_patch={
                    **build_activity_revive_meta_patch(reason=pending_reason),
                    "limited_time_outcome": "partial_success" if failed_pdd or not success else "success",
                },
            )

    logger.info(
        "pipeline %s batch lt retry finished batch=%s success_count=%s finalized=%s",
        row.pipeline_id,
        batch_index + 1,
        len(lt_success_pdd),
        finalized,
    )
    return True


def dispatch_batch_limited_time_retry_queue_task_finished(
    row,
    *,
    agent: str,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    if row is None:
        return False
    if str(agent or "").strip() != AgentKind.CAMPAIGN.value:
        return False
    return maybe_handle_batch_limited_time_retry_finished(
        row,
        run_id=run_id,
        success=success,
        result=result if isinstance(result, dict) else {},
        error=error,
    )

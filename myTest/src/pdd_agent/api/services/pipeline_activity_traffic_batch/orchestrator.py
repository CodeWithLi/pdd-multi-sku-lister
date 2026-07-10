"""
原始整合链路 — 活动 / 推广按商品数分批。

每批：活动 1 → 活动 2 → … → 推广（同一批商品），再进入下一批。
仅当 meta 开启且不与 LTTA / 每批活动推广 冲突时生效。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.api.services.pipeline_activity_traffic_batch.constants import (
    DEFAULT_BATCH_SIZE,
    META_BATCH_SIZE_KEY,
    META_ENABLED_KEY,
    META_STATE_KEY,
    PHASE_ACTIVITY,
    PHASE_DONE,
    PHASE_TRAFFIC,
)
from pdd_agent.api.services.task_runner import create_traffic_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import enqueue_task, get_integrated_pipeline, update_integrated_pipeline
from pdd_agent.domain.enums import AgentKind

logger = get_logger(__name__)


def activity_traffic_batch_meta_patch(*, enabled: bool, batch_size: int = DEFAULT_BATCH_SIZE) -> dict[str, Any]:
    if not enabled:
        return {}
    size = max(1, min(500, int(batch_size or DEFAULT_BATCH_SIZE)))
    return {
        META_ENABLED_KEY: True,
        META_BATCH_SIZE_KEY: size,
    }


def _meta(row) -> dict[str, Any]:
    return dict(getattr(row, "meta", None) or {})


def _state(row) -> dict[str, Any]:
    return dict(_meta(row).get(META_STATE_KEY) or {})


def _batch_size(row) -> int:
    return max(1, int(_meta(row).get(META_BATCH_SIZE_KEY) or DEFAULT_BATCH_SIZE))


def _conflicts(row) -> bool:
    meta = _meta(row)
    if meta.get("listing_per_batch_lt_traffic_activity_enabled"):
        return True
    if meta.get("listing_per_batch_campaign_enabled"):
        return True
    return False


def is_activity_traffic_batch_enabled(row) -> bool:
    return bool(_meta(row).get(META_ENABLED_KEY))


def is_activity_traffic_batch_active(row) -> bool:
    if not is_activity_traffic_batch_enabled(row):
        return False
    state = _state(row)
    return bool(state.get("enabled") and state.get("chunks"))


def _chunk_products(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    batch_size: int,
) -> list[dict[str, list[str]]]:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        resolve_mapping_ids_for_pdd_products,
    )

    pdd_ids = list(dict.fromkeys(str(x).strip() for x in pdd_ids if str(x).strip()))
    if not pdd_ids:
        return []
    if not mapping_ids or len(mapping_ids) != len(pdd_ids):
        mapping_ids = resolve_mapping_ids_for_pdd_products(
            str(row.account_id or ""),
            pdd_ids,
            fallback_mapping_ids=list(mapping_ids or []),
        )
    chunks: list[dict[str, list[str]]] = []
    for index in range(0, len(pdd_ids), batch_size):
        chunk_pdd = pdd_ids[index : index + batch_size]
        chunk_map = mapping_ids[index : index + batch_size]
        chunks.append(
            {
                "pdd_product_ids": chunk_pdd,
                "mapping_ids": chunk_map,
            }
        )
    return chunks


def _current_chunk(state: dict[str, Any]) -> dict[str, list[str]] | None:
    chunks = list(state.get("chunks") or [])
    index = int(state.get("chunk_index") or 0)
    if 0 <= index < len(chunks):
        chunk = chunks[index]
        if isinstance(chunk, dict):
            return {
                "pdd_product_ids": list(chunk.get("pdd_product_ids") or []),
                "mapping_ids": list(chunk.get("mapping_ids") or []),
            }
    return None


def _build_initial_state(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
) -> dict[str, Any]:
    batch_size = _batch_size(row)
    chunks = _chunk_products(row, pdd_ids=pdd_ids, mapping_ids=mapping_ids, batch_size=batch_size)
    return {
        "enabled": True,
        "batch_size": batch_size,
        "chunks": chunks,
        "chunk_index": 0,
        "activity_index": 0,
        "phase": PHASE_ACTIVITY,
        "total_chunks": len(chunks),
    }


def _schedule_campaign_for_chunk(
    row,
    *,
    activity_index: int,
    chunk: dict[str, list[str]],
    scheduled_at: datetime,
    meta_patch: dict[str, Any] | None = None,
) -> None:
    from pdd_agent.api.services.pipeline_service import _schedule_pipeline_campaign

    pdd_ids = list(chunk.get("pdd_product_ids") or [])
    mapping_ids = list(chunk.get("mapping_ids") or [])
    patch = dict(meta_patch or {})
    patch[META_STATE_KEY] = _state(row)
    patch["activity_traffic_batch_display"] = (
        f"活动/推广分批 {int(_state(row).get('chunk_index') or 0) + 1}/"
        f"{int(_state(row).get('total_chunks') or 0)}（本批 {len(pdd_ids)} 个商品）"
    )
    _schedule_pipeline_campaign(
        row,
        activity_index=activity_index,
        scheduled_at=scheduled_at,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        meta_patch=patch,
    )


def _enqueue_traffic_for_chunk(
    row,
    *,
    chunk: dict[str, list[str]],
    meta_patch: dict[str, Any] | None = None,
) -> None:
    pdd_ids = list(chunk.get("pdd_product_ids") or [])
    mapping_ids = list(chunk.get("mapping_ids") or [])
    traffic_run_id = create_traffic_run(row.account_id)
    enqueue_task(
        agent=AgentKind.TRAFFIC.value,
        run_id=traffic_run_id,
        account_id=row.account_id,
        payload={
            "pipeline_id": row.pipeline_id,
            "traffic_type": "promotion_create",
            "pdd_product_ids": pdd_ids,
            "published_mapping_ids": mapping_ids,
        },
        scheduled_at=datetime.now(),
    )
    state = dict(_state(row))
    state["phase"] = PHASE_TRAFFIC
    patch = dict(meta_patch or {})
    patch[META_STATE_KEY] = state
    patch["traffic_enqueued"] = True
    patch["traffic_finish_handled"] = False
    patch["activity_traffic_batch_display"] = (
        f"活动/推广分批 {int(state.get('chunk_index') or 0) + 1}/"
        f"{int(state.get('total_chunks') or 0)} 推广中（本批 {len(pdd_ids)} 个商品）"
    )
    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="traffic_queued",
        traffic_run_id=traffic_run_id,
        pdd_product_ids=pdd_ids,
        mapping_ids=mapping_ids,
        error="",
        meta_patch=patch,
    )
    logger.info(
        "pipeline %s activity_traffic_batch traffic queued chunk=%s/%s pdd_ids=%s run_id=%s",
        row.pipeline_id,
        int(state.get("chunk_index") or 0) + 1,
        int(state.get("total_chunks") or 0),
        len(pdd_ids),
        traffic_run_id,
    )


def _complete_pipeline(row, *, meta_patch: dict[str, Any] | None = None) -> None:
    state = dict(_state(row))
    state["phase"] = PHASE_DONE
    patch = dict(meta_patch or {})
    patch[META_STATE_KEY] = state
    patch.pop("activity_traffic_batch_display", None)
    update_integrated_pipeline(
        row.pipeline_id,
        status="completed",
        current_step="completed",
        error="",
        meta_patch=patch,
    )
    from pdd_agent.api.services.pipeline_mq_auto_phase2 import maybe_complete_mq_phase2

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    maybe_complete_mq_phase2(refreshed)
    logger.info("pipeline %s activity_traffic_batch all chunks completed", row.pipeline_id)


def _start_next_chunk_activity(
    row,
    *,
    meta_patch: dict[str, Any] | None = None,
) -> bool:
    state = dict(_state(row))
    next_chunk_index = int(state.get("chunk_index") or 0) + 1
    total = int(state.get("total_chunks") or 0)
    if next_chunk_index >= total:
        _complete_pipeline(row, meta_patch=meta_patch)
        return False

    state["chunk_index"] = next_chunk_index
    state["activity_index"] = 0
    state["phase"] = PHASE_ACTIVITY
    patch = dict(meta_patch or {})
    patch[META_STATE_KEY] = state
    patch["traffic_finish_handled"] = False
    patch["traffic_enqueued"] = False
    patch["campaign_activity_index"] = 0
    update_integrated_pipeline(row.pipeline_id, meta_patch=patch)
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    chunk = _current_chunk(_state(refreshed))
    if not chunk or not chunk.get("pdd_product_ids"):
        logger.warning("pipeline %s activity_traffic_batch empty chunk index=%s", row.pipeline_id, next_chunk_index)
        return _start_next_chunk_activity(refreshed, meta_patch=patch)

    patch["activity_traffic_batch_display"] = (
        f"活动/推广分批 {next_chunk_index + 1}/{total}（本批 {len(chunk['pdd_product_ids'])} 个商品）"
    )
    _schedule_campaign_for_chunk(
        refreshed,
        activity_index=0,
        chunk=chunk,
        scheduled_at=datetime.now(),
        meta_patch=patch,
    )
    logger.info(
        "pipeline %s activity_traffic_batch started chunk=%s/%s products=%s",
        row.pipeline_id,
        next_chunk_index + 1,
        total,
        len(chunk.get("pdd_product_ids") or []),
    )
    return True


def maybe_start_after_limited_time(
    row,
    *,
    meta_patch: dict[str, Any] | None = None,
    pdd_ids: list[str] | None = None,
    mapping_ids: list[str] | None = None,
) -> bool:
    """限时全部完成后拦截：初始化分批并预约第 1 批第 1 个活动。"""
    if not row or not is_activity_traffic_batch_enabled(row) or _conflicts(row):
        return False

    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        resolve_activity_product_ids_for_row,
    )
    from pdd_agent.api.services.pipeline_service import (
        _resolve_activity_delay,
        resolve_activity_scheduled_at,
    )

    resolved_pdd = list(pdd_ids or [])
    resolved_map = list(mapping_ids or [])
    if not resolved_pdd:
        resolved_pdd, resolved_map = resolve_activity_product_ids_for_row(row)
    if not resolved_pdd:
        logger.warning("pipeline %s activity_traffic_batch skip: no products", row.pipeline_id)
        return False

    state = _build_initial_state(row, pdd_ids=resolved_pdd, mapping_ids=resolved_map)
    if not state.get("chunks"):
        return False

    scheduled_at = resolve_activity_scheduled_at(
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )
    base_at = datetime.now() + _resolve_activity_delay(
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )
    patch = dict(meta_patch or {})
    patch["activity_jitter_seconds"] = max(0, int((scheduled_at - base_at).total_seconds()))
    patch[META_STATE_KEY] = state
    patch["campaign_activity_index"] = 0
    patch["activity_traffic_batch_display"] = (
        f"活动/推广分批 1/{state['total_chunks']}（每批 {state['batch_size']} 个，"
        f"共 {len(resolved_pdd)} 个商品）"
    )

    chunk = _current_chunk(state)
    if not chunk:
        return False

    update_integrated_pipeline(row.pipeline_id, meta_patch=patch)
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    _schedule_campaign_for_chunk(
        refreshed,
        activity_index=0,
        chunk=chunk,
        scheduled_at=scheduled_at,
        meta_patch=patch,
    )
    logger.info(
        "pipeline %s activity_traffic_batch initialized chunks=%s batch_size=%s products=%s scheduled_at=%s",
        row.pipeline_id,
        state["total_chunks"],
        state["batch_size"],
        len(resolved_pdd),
        scheduled_at,
    )
    return True


def _after_chunk_activities_done(
    row,
    *,
    meta_patch: dict[str, Any],
) -> None:
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    chunk = _current_chunk(_state(refreshed))
    if not chunk:
        _complete_pipeline(refreshed, meta_patch=meta_patch)
        return

    if not bool(getattr(refreshed, "auto_promotion", False)):
        from pdd_agent.api.services.pipeline_service import _pipeline_activity_ids

        meta_patch["campaign_activity_index"] = len(_pipeline_activity_ids(refreshed))
        update_integrated_pipeline(refreshed.pipeline_id, meta_patch=meta_patch)
        _start_next_chunk_activity(refreshed, meta_patch=meta_patch)
        return

    _enqueue_traffic_for_chunk(refreshed, chunk=chunk, meta_patch=meta_patch)


def maybe_handle_campaign_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    if not is_activity_traffic_batch_active(row):
        return False
    if str(getattr(row, "campaign_run_id", "") or "").strip() != str(run_id or "").strip():
        return False

    state = _state(row)
    if state.get("phase") != PHASE_ACTIVITY:
        return False

    from pdd_agent.api.services.pipeline_service import (
        _append_campaign_result,
        _campaign_activity_index,
        _campaign_run_already_handled,
        _format_multi_campaign_skip_reason,
        _mark_campaign_run_handled,
        _pipeline_activity_ids,
        _pipeline_continue_after_activity_failure,
        _should_skip_campaign_for_traffic,
        _summarize_run_message,
    )

    if _campaign_run_already_handled(row, run_id):
        return True

    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        maybe_record_campaign_finished,
    )

    maybe_record_campaign_finished(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )

    activity_ids = _pipeline_activity_ids(row)
    activity_index = int(state.get("activity_index") if state.get("activity_index") is not None else _campaign_activity_index(row))
    current_activity_id = (
        activity_ids[activity_index] if activity_index < len(activity_ids) else str(row.activity_id or "")
    )
    activity_skipped = (not success) and _should_skip_campaign_for_traffic(result, error)
    activity_continue = (
        (not success)
        and not activity_skipped
        and _pipeline_continue_after_activity_failure(row)
    )
    campaign_summary = _summarize_run_message(run_id)
    meta_patch: dict[str, Any] = {"campaign_summary": campaign_summary}
    _mark_campaign_run_handled(meta_patch, run_id)

    if not success and not activity_skipped and not activity_continue:
        _append_campaign_result(
            meta_patch,
            row,
            activity_id=current_activity_id,
            run_id=run_id,
            success=False,
            skipped=False,
            error=error or "活动报名失败",
            summary=campaign_summary,
        )
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="activity_failed",
            error=error or "活动报名失败",
            meta_patch=meta_patch,
        )
        return True

    _append_campaign_result(
        meta_patch,
        row,
        activity_id=current_activity_id,
        run_id=run_id,
        success=bool(success),
        skipped=activity_skipped,
        error=error if (activity_skipped or activity_continue) else "",
        summary=campaign_summary,
    )

    if activity_skipped:
        from pdd_agent.api.services.pipeline_service import _campaign_skip_message, _campaign_skip_outcome

        skip_reason = _campaign_skip_message(result, error)
        meta_patch["campaign_outcome"] = _campaign_skip_outcome(result)
        meta_patch["campaign_skip_reason"] = _format_multi_campaign_skip_reason(row, meta_patch, skip_reason)
    elif activity_continue:
        meta_patch["campaign_outcome"] = "activity_failed_continue"
        meta_patch["campaign_skip_reason"] = _format_multi_campaign_skip_reason(
            row,
            meta_patch,
            error or "活动报名失败",
        )
        update_integrated_pipeline(
            row.pipeline_id,
            status="running",
            current_step="activity_failed_continue",
            error="",
            meta_patch=meta_patch,
        )

    next_activity_index = activity_index + 1
    state = dict(_state(row))
    state["activity_index"] = next_activity_index
    meta_patch[META_STATE_KEY] = state

    if next_activity_index < len(activity_ids):
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        chunk = _current_chunk(_state(refreshed))
        if not chunk:
            return True
        update_integrated_pipeline(refreshed.pipeline_id, meta_patch=meta_patch)
        refreshed = get_integrated_pipeline(refreshed.pipeline_id) or refreshed
        _schedule_campaign_for_chunk(
            refreshed,
            activity_index=next_activity_index,
            chunk=chunk,
            scheduled_at=datetime.now(),
            meta_patch=meta_patch,
        )
        logger.info(
            "pipeline %s activity_traffic_batch next activity %s chunk=%s/%s",
            row.pipeline_id,
            activity_ids[next_activity_index],
            int(state.get("chunk_index") or 0) + 1,
            int(state.get("total_chunks") or 0),
        )
        return True

    meta_patch["campaign_activity_index"] = len(activity_ids)
    update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    _after_chunk_activities_done(refreshed, meta_patch=meta_patch)
    return True


def maybe_handle_traffic_finished(
    row,
    *,
    run_id: str,
    success: bool,
    error: str,
) -> bool:
    if not is_activity_traffic_batch_active(row):
        return False
    if str(getattr(row, "traffic_run_id", "") or "").strip() != str(run_id or "").strip():
        return False

    state = _state(row)
    if state.get("phase") != PHASE_TRAFFIC:
        return False

    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge import (
        maybe_record_traffic_finished,
    )

    maybe_record_traffic_finished(
        row,
        run_id=run_id,
        success=success,
        error=error,
    )

    meta = dict(row.meta or {})
    if meta.get("traffic_finish_handled"):
        return True

    if not success:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="traffic_failed",
            error=error or "推广创建失败",
            meta_patch={"traffic_finish_handled": True},
        )
        return True

    meta_patch: dict[str, Any] = {
        "traffic_summary": __import__(
            "pdd_agent.api.services.pipeline_service",
            fromlist=["_summarize_run_message"],
        )._summarize_run_message(run_id),
    }
    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="activity_traffic_batch_between_chunks",
        error="",
        meta_patch=meta_patch,
    )

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    total = int(_state(refreshed).get("total_chunks") or 0)
    chunk_index = int(_state(refreshed).get("chunk_index") or 0)
    if chunk_index + 1 >= total:
        patch = dict(meta_patch)
        patch["traffic_finish_handled"] = True
        _complete_pipeline(refreshed, meta_patch=patch)
        from pdd_agent.api.services.pipeline_mq_auto_phase2 import (
            maybe_complete_mq_phase2_on_traffic_finished,
        )

        maybe_complete_mq_phase2_on_traffic_finished(get_integrated_pipeline(row.pipeline_id) or row)
        return True

    patch = dict(meta_patch)
    patch["traffic_finish_handled"] = True
    _start_next_chunk_activity(refreshed, meta_patch=patch)
    return True


def resolve_activity_traffic_batch_step_hint(row) -> str:
    if not is_activity_traffic_batch_active(row):
        meta = _meta(row)
        if is_activity_traffic_batch_enabled(row) and meta.get("activity_traffic_batch_display"):
            return str(meta.get("activity_traffic_batch_display") or "")
        return ""
    return str(_meta(row).get("activity_traffic_batch_display") or "")

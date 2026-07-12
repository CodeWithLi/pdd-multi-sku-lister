"""
标准整合链路 — 每批上架成功后，限时限量购按商品数再拆成多趟。

规则：
- 子趟之间紧接着跑（仅几秒延迟）；
- 某一趟失败：该趟商品记失败，继续下一趟；
- 全部子趟完成后，才视为「本批上架批次的限时完成」，再进入下一批上架 / 聚合记录。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.api.services.pipeline_per_batch_lt_chunks.constants import (
    DEFAULT_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    META_AGGREGATE_RUN_ID_KEY,
    META_BATCH_SIZE_KEY,
    META_BATCH_SUCCESS_COUNT_KEY,
    META_BATCH_TOTAL_COUNT_KEY,
    META_DISPLAY_KEY,
    META_RETRY_AGGREGATE_KEY,
    META_STATE_KEY,
    MODE_BATCH_RETRY,
    MODE_LISTING_BATCH,
    POST_CHUNK_DELAY_SECONDS,
)
from pdd_agent.api.services.task_runner import create_campaign_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import enqueue_task, get_integrated_pipeline, update_integrated_pipeline
from pdd_agent.domain.enums import AgentKind

logger = get_logger(__name__)


def _meta(row) -> dict[str, Any]:
    raw = getattr(row, "meta", None) if row is not None else None
    return dict(raw) if isinstance(raw, dict) else {}


def _chunk_state(row) -> dict[str, Any]:
    state = _meta(row).get(META_STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _throttle_state(row) -> dict[str, Any]:
    return dict(_meta(row).get("listing_throttle") or {})


def _merge_unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def is_standard_per_batch_lt_chunk_pipeline(row) -> bool:
    """仅标准「每批限时 + 最后统一活动」，不含每批活动/推广、LTTA。"""
    if not row:
        return False
    meta = _meta(row)
    if not meta.get("listing_per_batch_limited_time_enabled"):
        return False
    if meta.get("listing_per_batch_lt_traffic_activity_enabled"):
        return False
    if meta.get("listing_per_batch_campaign_enabled"):
        return False
    throttle = _throttle_state(row)
    if not throttle.get("enabled"):
        return False
    return int(throttle.get("total_batches") or 0) > 1


def resolve_chunk_size(row) -> int:
    size = int(_meta(row).get(META_BATCH_SIZE_KEY) or DEFAULT_CHUNK_SIZE)
    return max(1, min(MAX_CHUNK_SIZE, size))


def per_batch_lt_chunks_meta_patch(*, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict[str, Any]:
    size = max(1, min(MAX_CHUNK_SIZE, int(chunk_size or DEFAULT_CHUNK_SIZE)))
    return {META_BATCH_SIZE_KEY: size}


def is_limited_time_chunk_sequence_active(row) -> bool:
    state = _chunk_state(row)
    return bool(state.get("enabled") and state.get("chunks"))


def build_product_chunks(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    batch_size: int | None = None,
) -> list[dict[str, list[str]]]:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        resolve_mapping_ids_for_pdd_products,
    )

    size = max(1, int(batch_size or resolve_chunk_size(row)))
    pdd_ids = _merge_unique(list(pdd_ids or []))
    if not pdd_ids:
        return []
    mapping_ids = list(mapping_ids or [])
    if not mapping_ids or len(mapping_ids) != len(pdd_ids):
        mapping_ids = resolve_mapping_ids_for_pdd_products(
            str(row.account_id or ""),
            pdd_ids,
            fallback_mapping_ids=mapping_ids,
        )
    chunks: list[dict[str, list[str]]] = []
    for index in range(0, len(pdd_ids), size):
        chunk_pdd = pdd_ids[index : index + size]
        chunk_map = mapping_ids[index : index + size]
        chunks.append(
            {
                "pdd_product_ids": chunk_pdd,
                "mapping_ids": chunk_map,
            }
        )
    return chunks


def format_chunk_display(
    *,
    listing_batch_index: int,
    chunk_index: int,
    total_chunks: int,
    batch_size: int,
) -> str:
    return (
        f"上架第 {listing_batch_index + 1} 批 · 限时 {chunk_index + 1}/{total_chunks} 趟"
        f"（每趟最多 {batch_size} 个）"
    )


def build_chunk_display_from_row(row) -> str:
    state = _chunk_state(row)
    if not state.get("enabled"):
        return str(_meta(row).get(META_DISPLAY_KEY) or "")
    listing_batch_index = int(state.get("listing_batch_index") or 0)
    chunk_index = int(state.get("chunk_index") or 0)
    total_chunks = int(state.get("total_chunks") or 0)
    batch_size = int(state.get("batch_size") or resolve_chunk_size(row))
    if total_chunks <= 0:
        return ""
    return format_chunk_display(
        listing_batch_index=listing_batch_index,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        batch_size=batch_size,
    )


def resolve_limited_time_step_chunk_hint(row) -> str | None:
    if not is_limited_time_chunk_sequence_active(row):
        display = str(_meta(row).get(META_DISPLAY_KEY) or "").strip()
        return display or None
    return build_chunk_display_from_row(row) or None


def _save_chunk_state(row, patch: dict[str, Any], *, display: str = "") -> None:
    current = _chunk_state(row)
    current.update(patch)
    meta_patch: dict[str, Any] = {META_STATE_KEY: current}
    if display:
        meta_patch[META_DISPLAY_KEY] = display
    update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)


def _clear_chunk_state(row) -> None:
    update_integrated_pipeline(
        row.pipeline_id,
        meta_patch={
            META_STATE_KEY: None,
            META_DISPLAY_KEY: "",
        },
    )


def _current_chunk(state: dict[str, Any]) -> dict[str, list[str]] | None:
    chunks = list(state.get("chunks") or [])
    index = int(state.get("chunk_index") or 0)
    if 0 <= index < len(chunks) and isinstance(chunks[index], dict):
        return {
            "pdd_product_ids": list(chunks[index].get("pdd_product_ids") or []),
            "mapping_ids": list(chunks[index].get("mapping_ids") or []),
        }
    return None


def _enqueue_limited_time_chunk(
    row,
    *,
    chunk: dict[str, list[str]],
    meta_patch: dict[str, Any],
    scheduled_at: datetime | None = None,
    retry_batch_index: int | None = None,
) -> str:
    pdd_ids = list(chunk.get("pdd_product_ids") or [])
    mapping_ids = list(chunk.get("mapping_ids") or [])
    when = scheduled_at or (datetime.now() + timedelta(seconds=POST_CHUNK_DELAY_SECONDS))

    if retry_batch_index is not None:
        limited_time_run_id = create_campaign_run(str(row.account_id or ""))
        enqueue_task(
            agent=AgentKind.CAMPAIGN.value,
            run_id=limited_time_run_id,
            account_id=str(row.account_id or ""),
            payload={
                "pipeline_id": row.pipeline_id,
                "campaign_type": "limited_time_setup",
                "pdd_product_ids": pdd_ids,
                "published_mapping_ids": mapping_ids,
                "pipeline_batch_limited_time_retry": True,
                "pipeline_batch_limited_time_retry_batch_index": int(retry_batch_index),
            },
            scheduled_at=when,
        )
        patch = dict(meta_patch or {})
        patch["limited_time_run_id"] = limited_time_run_id
        patch.pop("limited_time_finish_handled", None)
        is_future = when > datetime.now()
        update_integrated_pipeline(
            row.pipeline_id,
            status="running",
            current_step="batch_limited_time_retry",
            pdd_product_ids=pdd_ids,
            mapping_ids=mapping_ids,
            error="",
            meta_patch=patch,
        )
        from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
            _save_batch_lt_retry_state,
        )

        _save_batch_lt_retry_state(
            row,
            {
                "limited_time_run_id": limited_time_run_id,
                "active_batch_index": int(retry_batch_index),
            },
        )
        return limited_time_run_id

    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        _enqueue_limited_time_for_batch,
    )

    return _enqueue_limited_time_for_batch(
        row,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        meta_patch=meta_patch,
        scheduled_at=when,
    )


def _record_chunk_product_tracker(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
    batch_index: int,
    chunk_pdd_ids: list[str],
    chunk_mapping_ids: list[str],
) -> tuple[list[str], list[str]]:
    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import record_limited_time_batch

    lt_success_pdd, lt_success_mapping, failed_pdd = _resolve_chunk_lt_success(
        row,
        run_id=run_id,
        result=result,
        batch_pdd_ids=chunk_pdd_ids,
        batch_mapping_ids=chunk_mapping_ids,
    )
    record_limited_time_batch(
        pipeline_id=row.pipeline_id,
        batch_index=batch_index,
        success_pdd_ids=lt_success_pdd,
        failed_pdd_ids=failed_pdd,
        batch_failed=not success and not lt_success_pdd,
        error=error or "限时限量购设置失败",
    )
    return lt_success_pdd, lt_success_mapping


def _resolve_chunk_lt_success(
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


def _merge_chunk_success_into_state(
    state: dict[str, Any],
    *,
    lt_success_pdd: list[str],
    lt_success_mapping: list[str],
) -> dict[str, Any]:
    merged_pdd = _merge_unique([*(state.get("chunk_success_pdd_ids") or []), *lt_success_pdd])
    merged_map = _merge_unique([*(state.get("chunk_success_mapping_ids") or []), *lt_success_mapping])
    return {
        **state,
        "chunk_success_pdd_ids": merged_pdd,
        "chunk_success_mapping_ids": merged_map,
    }


def _seed_aggregate_meta_before_final_record(row, state: dict[str, Any]) -> None:
    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.constants import (
        AGG_MAPPING_IDS_KEY,
        AGG_PDD_IDS_KEY,
    )

    meta = _meta(row)
    prior_pdd = _merge_unique(
        [
            *(_meta(row).get(AGG_PDD_IDS_KEY) or []),
            *(state.get("chunk_success_pdd_ids") or []),
        ]
    )
    prior_map = _merge_unique(
        [
            *(_meta(row).get(AGG_MAPPING_IDS_KEY) or []),
            *(state.get("chunk_success_mapping_ids") or []),
        ]
    )
    if not prior_pdd and not prior_map:
        return
    update_integrated_pipeline(
        row.pipeline_id,
        meta_patch={
            AGG_PDD_IDS_KEY: prior_pdd,
            AGG_MAPPING_IDS_KEY: prior_map,
        },
    )


def maybe_start_chunked_limited_time_after_listing(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_meta: dict[str, Any] | None,
) -> bool:
    """
    上架批次完成后：若商品数超过每趟上限，拆成多趟限时并只入队第一趟。
    返回 True 表示已接管（含入队）。
    """
    if not is_standard_per_batch_lt_chunk_pipeline(row):
        return False
    if not bool(_meta(row).get("auto_limited_time_setup")):
        return False

    batch_size = resolve_chunk_size(row)
    chunks = build_product_chunks(row, pdd_ids=pdd_ids, mapping_ids=mapping_ids, batch_size=batch_size)
    if len(chunks) <= 1:
        return False

    from pdd_agent.api.services.pipeline_listing_throttle import (
        _throttle_base_from_meta,
        has_more_listing_batches,
        merge_throttle_accumulated_products,
    )
    from pdd_agent.api.services.pipeline_per_batch_limited_time import META_STATE_KEY as LT_META_STATE_KEY

    throttle = _throttle_state(row)
    base_throttle = _throttle_base_from_meta(throttle, listing_meta)
    batch_index = int(base_throttle.get("batch_index") or 0)
    merged_pdd, merged_map = merge_throttle_accumulated_products(
        base_throttle,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    )
    more_batches = has_more_listing_batches(base_throttle)
    interval_minutes = max(1, int(base_throttle.get("interval_minutes") or 1))

    meta_patch = dict(listing_meta or {})
    meta_patch["listing_throttle"] = {
        **base_throttle,
        "accumulated_pdd_ids": merged_pdd,
        "accumulated_mapping_ids": merged_map,
    }

    per_batch_patch: dict[str, Any] = {
        "enabled": True,
        "last_batch_index": batch_index,
        "awaiting_final_activity": not more_batches,
    }
    if more_batches:
        per_batch_patch["pending"] = {
            "next_batch_index": batch_index + 1,
            "interval_minutes": interval_minutes,
        }
    else:
        per_batch_patch.pop("pending", None)
        meta_patch["listing_throttle"]["batch_index"] = batch_index
        meta_patch["listing_throttle"]["completed"] = True

    meta_patch[LT_META_STATE_KEY] = per_batch_patch

    chunk_state: dict[str, Any] = {
        "enabled": True,
        "mode": MODE_LISTING_BATCH,
        "batch_size": batch_size,
        "listing_batch_index": batch_index,
        "chunks": chunks,
        "chunk_index": 0,
        "total_chunks": len(chunks),
        "chunk_success_pdd_ids": [],
        "chunk_success_mapping_ids": [],
        "listing_batch_pdd_ids": pdd_ids,
    }
    display = format_chunk_display(
        listing_batch_index=batch_index,
        chunk_index=0,
        total_chunks=len(chunks),
        batch_size=batch_size,
    )
    meta_patch[META_STATE_KEY] = chunk_state
    meta_patch[META_DISPLAY_KEY] = display

    first_chunk = chunks[0]
    run_id = _enqueue_limited_time_chunk(
        row,
        chunk=first_chunk,
        meta_patch=meta_patch,
    )
    logger.info(
        "pipeline %s per-batch LT chunks started listing_batch=%s chunk=1/%s run_id=%s pdd_ids=%s",
        row.pipeline_id,
        batch_index + 1,
        len(chunks),
        run_id,
        first_chunk.get("pdd_product_ids"),
    )
    return True


def maybe_start_chunked_batch_limited_time_retry(
    row,
    *,
    batch_index: int,
    pdd_ids: list[str],
    mapping_ids: list[str],
) -> str | None:
    """分批限时重跑：目标商品超过每趟上限时拆成多趟。返回 run_id 或 None。"""
    if not is_standard_per_batch_lt_chunk_pipeline(row):
        return None

    batch_size = resolve_chunk_size(row)
    chunks = build_product_chunks(row, pdd_ids=pdd_ids, mapping_ids=mapping_ids, batch_size=batch_size)
    if len(chunks) <= 1:
        return None

    chunk_state: dict[str, Any] = {
        "enabled": True,
        "mode": MODE_BATCH_RETRY,
        "batch_size": batch_size,
        "listing_batch_index": int(batch_index),
        "chunks": chunks,
        "chunk_index": 0,
        "total_chunks": len(chunks),
        "chunk_success_pdd_ids": [],
        "chunk_success_mapping_ids": [],
    }
    display = format_chunk_display(
        listing_batch_index=int(batch_index),
        chunk_index=0,
        total_chunks=len(chunks),
        batch_size=batch_size,
    )
    meta_patch = {
        META_STATE_KEY: chunk_state,
        META_DISPLAY_KEY: display,
    }
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        POLICY_META_FLAG,
        PHASE_LIMITED_TIME,
        _save_batch_lt_retry_state,
    )

    _save_batch_lt_retry_state(
        row,
        {
            POLICY_META_FLAG: True,
            "enabled": True,
            "phase": PHASE_LIMITED_TIME,
            "active_batch_index": int(batch_index),
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

    first_chunk = chunks[0]
    run_id = _enqueue_limited_time_chunk(
        row,
        chunk=first_chunk,
        meta_patch=meta_patch,
        retry_batch_index=int(batch_index),
    )
    logger.info(
        "pipeline %s batch LT retry chunks started batch=%s chunk=1/%s run_id=%s pdd_ids=%s",
        row.pipeline_id,
        batch_index + 1,
        len(chunks),
        run_id,
        first_chunk.get("pdd_product_ids"),
    )
    return run_id


def maybe_handle_limited_time_chunk_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    """
    限时子趟完成后调用。

    返回 True：已处理且 caller 应提前 return（还有下一子趟，或 retry 模式收尾中）。
    返回 False：非子趟模式，或本批上架批次的全部子趟已完成（caller 继续原聚合/推进逻辑）。
    """
    state = _chunk_state(row)
    if not state.get("enabled"):
        return False

    current_lt_run_id = str(_meta(row).get("limited_time_run_id") or "").strip()
    if current_lt_run_id != str(run_id or "").strip():
        return False

    chunk = _current_chunk(state)
    if not chunk:
        _clear_chunk_state(row)
        return False

    chunk_pdd = list(chunk.get("pdd_product_ids") or [])
    chunk_map = list(chunk.get("mapping_ids") or [])
    listing_batch_index = int(state.get("listing_batch_index") or 0)
    chunk_index = int(state.get("chunk_index") or 0)
    total_chunks = int(state.get("total_chunks") or 0)
    batch_size = int(state.get("batch_size") or resolve_chunk_size(row))
    mode = str(state.get("mode") or MODE_LISTING_BATCH)

    lt_success_pdd, lt_success_mapping = _record_chunk_product_tracker(
        row,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
        batch_index=listing_batch_index,
        chunk_pdd_ids=chunk_pdd,
        chunk_mapping_ids=chunk_map,
    )
    state = _merge_chunk_success_into_state(
        state,
        lt_success_pdd=lt_success_pdd,
        lt_success_mapping=lt_success_mapping,
    )

    failure_message = str(error or "").strip() or "限时限量购设置失败"
    if not success and lt_success_pdd:
        logger.warning(
            "pipeline %s LT chunk partial failure listing_batch=%s chunk=%s/%s run_id=%s error=%s success=%s",
            row.pipeline_id,
            listing_batch_index + 1,
            chunk_index + 1,
            total_chunks,
            run_id,
            failure_message[:200],
            len(lt_success_pdd),
        )
    elif not success:
        logger.warning(
            "pipeline %s LT chunk failed listing_batch=%s chunk=%s/%s run_id=%s error=%s",
            row.pipeline_id,
            listing_batch_index + 1,
            chunk_index + 1,
            total_chunks,
            run_id,
            failure_message[:200],
        )

    next_index = chunk_index + 1
    if next_index < total_chunks:
        state["chunk_index"] = next_index
        display = format_chunk_display(
            listing_batch_index=listing_batch_index,
            chunk_index=next_index,
            total_chunks=total_chunks,
            batch_size=batch_size,
        )
        next_chunk = _current_chunk(state)
        if not next_chunk:
            _clear_chunk_state(row)
            return False

        meta_patch: dict[str, Any] = {
            META_STATE_KEY: state,
            META_DISPLAY_KEY: display,
        }
        if not success:
            meta_patch["limited_time_outcome"] = "failed"
            meta_patch["per_batch_limited_time_last_error"] = failure_message

        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        next_run_id = _enqueue_limited_time_chunk(
            refreshed,
            chunk=next_chunk,
            meta_patch=meta_patch,
            retry_batch_index=listing_batch_index if mode == MODE_BATCH_RETRY else None,
        )
        logger.info(
            "pipeline %s per-batch LT next chunk listing_batch=%s chunk=%s/%s run_id=%s pdd_ids=%s",
            row.pipeline_id,
            listing_batch_index + 1,
            next_index + 1,
            total_chunks,
            next_run_id,
            next_chunk.get("pdd_product_ids"),
        )
        return True

    if mode == MODE_BATCH_RETRY:
        update_integrated_pipeline(
            row.pipeline_id,
            meta_patch={
                META_RETRY_AGGREGATE_KEY: {
                    "batch_index": listing_batch_index,
                    "run_id": str(run_id or "").strip(),
                    "chunk_success_pdd_ids": list(state.get("chunk_success_pdd_ids") or []),
                    "chunk_success_mapping_ids": list(state.get("chunk_success_mapping_ids") or []),
                    "last_chunk_success": bool(success),
                    "error": str(error or "").strip(),
                },
            },
        )
    else:
        _seed_aggregate_meta_before_final_record(row, state)
        update_integrated_pipeline(
            row.pipeline_id,
            meta_patch={
                META_AGGREGATE_RUN_ID_KEY: str(run_id or "").strip(),
                META_BATCH_SUCCESS_COUNT_KEY: len(state.get("chunk_success_pdd_ids") or []),
                META_BATCH_TOTAL_COUNT_KEY: len(state.get("listing_batch_pdd_ids") or []),
            },
        )

    _clear_chunk_state(row)
    logger.info(
        "pipeline %s per-batch LT chunks completed listing_batch=%s total_chunks=%s mode=%s",
        row.pipeline_id,
        listing_batch_index + 1,
        total_chunks,
        mode,
    )
    return False


def should_skip_lt_batch_tracker_for_aggregate(row, *, run_id: str) -> bool:
    meta = _meta(row)
    return str(meta.get(META_AGGREGATE_RUN_ID_KEY) or "").strip() == str(run_id or "").strip()


def clear_lt_batch_tracker_aggregate_flag(row) -> None:
    if _meta(row).get(META_AGGREGATE_RUN_ID_KEY):
        update_integrated_pipeline(
            row.pipeline_id,
            meta_patch={
                META_AGGREGATE_RUN_ID_KEY: None,
                META_BATCH_SUCCESS_COUNT_KEY: None,
                META_BATCH_TOTAL_COUNT_KEY: None,
            },
        )


def consume_chunk_retry_finish_context(row) -> dict[str, Any] | None:
    raw = _meta(row).get(META_RETRY_AGGREGATE_KEY)
    if not isinstance(raw, dict):
        return None
    update_integrated_pipeline(row.pipeline_id, meta_patch={META_RETRY_AGGREGATE_KEY: None})
    return dict(raw)


def merge_chunk_retry_success_into_activity_pool(
    row,
    *,
    lt_success_pdd: list[str],
    lt_success_mapping: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        META_ACTIVITY_PDD_IDS_KEY,
        META_LT_SUCCESS_MAPPING_IDS_KEY,
        META_LT_SUCCESS_PDD_IDS_KEY,
        LimitedTimeSuccessProducts,
        build_limited_time_success_meta_patch,
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
    merged_pdd = _merge_unique([*existing_pdd, *lt_success_pdd])
    merged_map = _merge_unique([*existing_map, *lt_success_mapping])
    patch = build_limited_time_success_meta_patch(
        LimitedTimeSuccessProducts(
            pdd_product_ids=merged_pdd,
            mapping_ids=merged_map,
            source="batch_limited_time_retry_success",
            detail=(
                f"分批限时重跑成功 {len(lt_success_pdd)} 个，"
                f"活动池合计 {len(merged_pdd)} 个"
            ),
        )
    )
    update_integrated_pipeline(row.pipeline_id, meta_patch=patch)
    return merged_pdd, merged_map, list(lt_success_pdd), list(lt_success_mapping)


def should_skip_aggregate_for_incomplete_chunks(row, *, run_id: str) -> bool:
    """子趟未完成时不应写入 batch_log。"""
    if not is_limited_time_chunk_sequence_active(row):
        return False
    current_lt_run_id = str(_meta(row).get("limited_time_run_id") or "").strip()
    return current_lt_run_id == str(run_id or "").strip()

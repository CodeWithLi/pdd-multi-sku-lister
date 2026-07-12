"""
标准整合链路：分批上架 + 每批限时限量购（非 LTTA / 非每批活动推广）。

- 每批限时结束后写入 batch_product_stages 表，并累计限时成功商品；
- 中间批失败不将整条链路标 failed，也不覆盖套图级限时进度；
- 最后一批结束后按「跨批累计」决定 waiting_activity 或 failed。
"""

from __future__ import annotations

from typing import Any, Callable

from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
    record_limited_time_batch,
    record_listing_batch_from_result,
)
from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.constants import (
    AGG_BATCH_COUNT_KEY,
    AGG_BATCH_LOG_KEY,
    AGG_FINALIZED_KEY,
    AGG_IN_PROGRESS_KEY,
    AGG_MAPPING_IDS_KEY,
    AGG_OUTCOME_KEY,
    AGG_PDD_IDS_KEY,
)
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, update_integrated_pipeline

logger = get_logger(__name__)


def _throttle_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get("listing_throttle") or {})


def _lt_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get("listing_per_batch_limited_time") or {})


def _merge_unique(values: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            merged.append(text)
    return merged


def _accumulated_pdd_ids(meta: dict[str, Any]) -> list[str]:
    raw = meta.get(AGG_PDD_IDS_KEY) or []
    if not isinstance(raw, list):
        return []
    return _merge_unique([str(item) for item in raw])


def _accumulated_mapping_ids(meta: dict[str, Any]) -> list[str]:
    raw = meta.get(AGG_MAPPING_IDS_KEY) or []
    if not isinstance(raw, list):
        return []
    return _merge_unique([str(item) for item in raw])


def _batch_log(meta: dict[str, Any]) -> list[dict[str, Any]]:
    raw = meta.get(AGG_BATCH_LOG_KEY) or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _entry_batch_index(item: dict[str, Any]) -> int:
    raw = item.get("batch_index")
    if raw is None:
        return -1
    return int(raw)


def _pipeline_activity_ids(row) -> list[str]:
    meta = dict(row.meta or {})
    ids = [str(item).strip() for item in (meta.get("activity_ids") or []) if str(item).strip()]
    if ids:
        return list(dict.fromkeys(ids))
    legacy = str(getattr(row, "activity_id", "") or "").strip()
    return [legacy] if legacy else []


def is_standard_per_batch_lt_pipeline(row) -> bool:
    """分批每批限时、且非 LTTA / 非每批活动推广。"""
    if not row:
        return False
    meta = dict(row.meta or {})
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


def _current_batch_index(row) -> int:
    lt_state = _lt_state(row)
    throttle = _throttle_state(row)
    if lt_state.get("last_batch_index") is not None:
        return int(lt_state.get("last_batch_index") or 0)
    return int(throttle.get("batch_index") or 0)


def _is_final_batch(row) -> bool:
    from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
        has_pending_throttled_listing_batches,
    )

    lt_state = _lt_state(row)
    if lt_state.get("awaiting_final_activity"):
        return True
    return not has_pending_throttled_listing_batches(row)


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
    return list(extract.pdd_product_ids), list(mapping_ids)


def record_listing_batch(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_result: dict[str, Any] | None,
) -> None:
    if not is_standard_per_batch_lt_pipeline(row):
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
    update_integrated_pipeline(
        row.pipeline_id,
        meta_patch={AGG_IN_PROGRESS_KEY: True},
    )


def _append_skipped_limited_time_batch_log(
    row,
    *,
    batch_index: int,
    skip_reason: str,
) -> dict[str, Any] | None:
    """空批跳过分批限时时写入 batch_log；已存在同批记录则返回 None。"""
    if not is_standard_per_batch_lt_pipeline(row):
        return None

    meta = dict(row.meta or {})
    batch_log = _batch_log(meta)
    if any(_entry_batch_index(item) == batch_index for item in batch_log):
        return None

    batch_count = int(meta.get(AGG_BATCH_COUNT_KEY) or 0) + 1
    batch_entry = {
        "batch_index": batch_index,
        "run_id": "",
        "success": True,
        "skipped": True,
        "batch_success_count": 0,
        "batch_failed_count": 0,
        "error": "",
        "skip_reason": str(skip_reason or "").strip() or "本批无成功上架商品",
    }
    batch_log = [item for item in batch_log if _entry_batch_index(item) != batch_index]
    batch_log.append(batch_entry)

    throttle = _throttle_state(row)
    total_batches = int(throttle.get("total_batches") or 0)
    more_batches = total_batches > 0 and batch_index + 1 < total_batches
    lt_state = _lt_state(row)
    per_batch_patch: dict[str, Any] = {
        "enabled": True,
        "last_batch_index": batch_index,
        "pending": None,
        "awaiting_final_activity": not more_batches,
    }

    meta_patch: dict[str, Any] = {
        AGG_BATCH_COUNT_KEY: batch_count,
        AGG_BATCH_LOG_KEY: batch_log,
        AGG_IN_PROGRESS_KEY: True,
        "listing_per_batch_limited_time": {
            **lt_state,
            **per_batch_patch,
        },
    }
    update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)
    logger.info(
        "pipeline %s std per-batch LT aggregate recorded skipped batch=%s reason=%s",
        row.pipeline_id,
        batch_index + 1,
        batch_entry["skip_reason"],
    )
    return meta_patch


def record_skipped_limited_time_batch_for_empty_listing(
    row,
    *,
    skip_reason: str = "本批无成功上架商品",
) -> bool:
    """
    分批上架本批无成功商品、跳过分批限时限量购时仍计入 batch_log。
    返回 True 表示已处理（含幂等跳过）。
    """
    if not is_standard_per_batch_lt_pipeline(row):
        return False

    throttle = _throttle_state(row)
    batch_index = int(throttle.get("batch_index") or 0)
    patch = _append_skipped_limited_time_batch_log(
        row,
        batch_index=batch_index,
        skip_reason=skip_reason,
    )
    return patch is not None or any(
        _entry_batch_index(item) == batch_index for item in _batch_log(dict(row.meta or {}))
    )


def backfill_missing_limited_time_batches(row) -> bool:
    """
    上架已全部完成但 batch_log 缺批时，将缺失批补记为 skipped。
    用于修复空批跳过限时导致进度卡在 N/M 的链路。
    """
    if not is_standard_per_batch_lt_pipeline(row):
        return False

    meta = dict(row.meta or {})
    if meta.get(AGG_FINALIZED_KEY):
        return False

    throttle = _throttle_state(row)
    if not throttle.get("completed"):
        return False

    total = int(throttle.get("total_batches") or 0)
    if total <= 0:
        return False

    batch_log = _batch_log(meta)
    recorded = {_entry_batch_index(item) for item in batch_log if _entry_batch_index(item) >= 0}
    missing = [index for index in range(total) if index not in recorded]
    if not missing:
        return False

    changed = False
    current = row
    for batch_index in missing:
        patch = _append_skipped_limited_time_batch_log(
            current,
            batch_index=batch_index,
            skip_reason="本批无成功上架商品（补记）",
        )
        if patch is not None:
            changed = True
            current = get_integrated_pipeline(row.pipeline_id) or current
    return changed


def record_limited_time_batch_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> Any:
    """
    每批限时结束后记录 DB + 累计成功商品；不决定整条链路终态。
    返回刷新后的 row。
    """
    if not is_standard_per_batch_lt_pipeline(row):
        return row

    current_lt_run_id = str((row.meta or {}).get("limited_time_run_id") or "").strip()
    if current_lt_run_id != str(run_id or "").strip():
        return row

    batch_index = _current_batch_index(row)
    batch_pdd_ids = list(row.pdd_product_ids or [])
    batch_mapping_ids = list(row.mapping_ids or [])

    from pdd_agent.api.services.pipeline_per_batch_lt_chunks.bridge import (
        clear_lt_batch_tracker_aggregate_flag,
        should_skip_lt_batch_tracker_for_aggregate,
    )

    skip_tracker = should_skip_lt_batch_tracker_for_aggregate(row, run_id=run_id)
    meta = dict(row.meta or {})
    if skip_tracker:
        last_chunk_pdd, last_chunk_mapping = _resolve_lt_success_products(
            row,
            run_id=run_id,
            result=result,
            batch_pdd_ids=batch_pdd_ids,
            batch_mapping_ids=batch_mapping_ids,
        )
        lt_success_pdd_ids = _merge_unique([*_accumulated_pdd_ids(meta), *last_chunk_pdd])
        lt_success_mapping_ids = _merge_unique(
            [*_accumulated_mapping_ids(meta), *last_chunk_mapping]
        )
        batch_success_count = int(meta.get("listing_per_batch_lt_chunks_batch_success_count") or 0)
        batch_total_count = int(meta.get("listing_per_batch_lt_chunks_batch_total_count") or 0)
        failed_pdd = max(0, batch_total_count - batch_success_count)
    else:
        lt_success_pdd_ids, lt_success_mapping_ids = _resolve_lt_success_products(
            row,
            run_id=run_id,
            result=result,
            batch_pdd_ids=batch_pdd_ids,
            batch_mapping_ids=batch_mapping_ids,
        )
        failed_pdd = [pid for pid in batch_pdd_ids if pid not in set(lt_success_pdd_ids)]
        batch_success_count = len(lt_success_pdd_ids)

        record_limited_time_batch(
            pipeline_id=row.pipeline_id,
            batch_index=batch_index,
            success_pdd_ids=lt_success_pdd_ids,
            failed_pdd_ids=failed_pdd,
            batch_failed=not success and not lt_success_pdd_ids,
            error=error or "限时限量购设置失败",
        )
    merged_pdd = _merge_unique([*_accumulated_pdd_ids(meta), *lt_success_pdd_ids])
    merged_mapping = _merge_unique([*_accumulated_mapping_ids(meta), *lt_success_mapping_ids])
    batch_count = int(meta.get(AGG_BATCH_COUNT_KEY) or 0) + 1
    batch_entry = {
        "batch_index": batch_index,
        "run_id": str(run_id or "").strip(),
        "success": bool(success),
        "batch_success_count": batch_success_count if skip_tracker else len(lt_success_pdd_ids),
        "batch_failed_count": failed_pdd if skip_tracker else len(failed_pdd),
        "error": str(error or "").strip(),
    }
    batch_log = [item for item in _batch_log(meta) if _entry_batch_index(item) != batch_index]
    batch_log.append(batch_entry)

    meta_patch: dict[str, Any] = {
        AGG_PDD_IDS_KEY: merged_pdd,
        AGG_MAPPING_IDS_KEY: merged_mapping,
        AGG_BATCH_COUNT_KEY: batch_count,
        AGG_BATCH_LOG_KEY: batch_log,
        AGG_IN_PROGRESS_KEY: True,
    }
    update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)
    if skip_tracker:
        clear_lt_batch_tracker_aggregate_flag(get_integrated_pipeline(row.pipeline_id) or row)
    logger.info(
        "pipeline %s std per-batch LT aggregate recorded batch=%s success_count=%s total=%s run_id=%s",
        row.pipeline_id,
        batch_index + 1,
        len(lt_success_pdd_ids),
        len(merged_pdd),
        run_id,
    )
    return get_integrated_pipeline(row.pipeline_id) or row


def restore_intermediate_lt_progress_meta(row) -> None:
    """中间批结束后清除会误导前端的整条链路 limited_time_outcome。"""
    if not is_standard_per_batch_lt_pipeline(row):
        return
    meta = dict(row.meta or {})
    if meta.get(AGG_FINALIZED_KEY):
        return
    if _is_final_batch(row):
        return
    patch: dict[str, Any] = {AGG_IN_PROGRESS_KEY: True}
    if meta.get("limited_time_outcome"):
        patch["limited_time_outcome"] = ""
    if meta.get("limited_time_skip_reason"):
        patch["limited_time_skip_reason"] = ""
    update_integrated_pipeline(row.pipeline_id, meta_patch=patch)


def maybe_finalize_after_all_batches(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
    schedule_activity_fn: Callable[..., None],
    advance_store_sequential_fn: Callable[[Any], None],
    summarize_run_message_fn: Callable[[str], str],
) -> bool:
    """
    最后一批限时结束后：按跨批累计决定预约活动或 failed。
    返回 True 表示已处理终态。
    """
    if not is_standard_per_batch_lt_pipeline(row):
        return False
    if not _is_final_batch(row):
        return False

    meta = dict(row.meta or {})
    accumulated_pdd = _accumulated_pdd_ids(meta)
    accumulated_mapping = _accumulated_mapping_ids(meta)
    failure_message = str(error or "").strip() or "限时限量购设置失败"
    summarize = summarize_run_message_fn(run_id)

    if not accumulated_pdd:
        return False

    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        build_limited_time_success_meta_patch,
        LimitedTimeSuccessProducts,
    )

    merged = LimitedTimeSuccessProducts(
        pdd_product_ids=accumulated_pdd,
        mapping_ids=accumulated_mapping,
        source="std_per_batch_lt_aggregate",
        detail=f"跨批累计限时成功 {len(accumulated_pdd)} 个商品（{int(meta.get(AGG_BATCH_COUNT_KEY) or 0)} 批）",
    )

    meta_patch: dict[str, Any] = {
        "limited_time_finish_handled": True,
        "limited_time_summary": summarize,
        AGG_FINALIZED_KEY: True,
        AGG_IN_PROGRESS_KEY: False,
    }
    meta_patch.update(build_limited_time_success_meta_patch(merged))
    meta_patch[AGG_PDD_IDS_KEY] = accumulated_pdd
    meta_patch[AGG_MAPPING_IDS_KEY] = accumulated_mapping

    if success and not error:
        outcome = "success"
        meta_patch[AGG_OUTCOME_KEY] = outcome
        meta_patch["limited_time_outcome"] = outcome
    else:
        outcome = "partial_success"
        meta_patch[AGG_OUTCOME_KEY] = outcome
        meta_patch["limited_time_outcome"] = outcome
        meta_patch["limited_time_skip_reason"] = (
            failure_message or "最后一批限时限量购失败，使用历史累计成功商品继续活动"
        )

    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="limited_time_success_continue",
        pdd_product_ids=accumulated_pdd,
        mapping_ids=accumulated_mapping,
        error="",
        meta_patch=meta_patch,
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    schedule_activity_fn(
        refreshed,
        meta_patch=meta_patch,
        pdd_ids=accumulated_pdd,
        mapping_ids=accumulated_mapping,
    )
    logger.info(
        "pipeline %s std per-batch LT aggregate finalized outcome=%s pdd_ids=%s",
        row.pipeline_id,
        outcome,
        accumulated_pdd,
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    advance_store_sequential_fn(refreshed)
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
        maybe_flush_batch_lt_retry_activity_reschedule,
    )

    maybe_flush_batch_lt_retry_activity_reschedule(refreshed)
    return True


def should_absorb_limited_time_task_failure(row, *, run_id: str) -> bool:
    """队列层失败吸收：已收尾或仍有跨批累计成功时不标整条 failed。"""
    if not is_standard_per_batch_lt_pipeline(row):
        return False
    meta = dict(row.meta or {})
    if meta.get("limited_time_finish_handled"):
        return True
    if meta.get(AGG_FINALIZED_KEY):
        return True
    if _accumulated_pdd_ids(meta) and _is_final_batch(row):
        return True
    current_lt_run_id = str(meta.get("limited_time_run_id") or "").strip()
    if current_lt_run_id != str(run_id or "").strip():
        return False
    if not _is_final_batch(row):
        return True
    return False


def resolve_limited_time_step_display(row) -> dict[str, Any] | None:
    """为 _step_infos 提供聚合后的限时限量购展示（覆盖单批 run 状态）。"""
    if not is_standard_per_batch_lt_pipeline(row):
        return None
    meta = dict(row.meta or {})
    batch_log = _batch_log(meta)
    total_batches = int(_throttle_state(row).get("total_batches") or 0)
    accumulated = len(_accumulated_pdd_ids(meta))
    finalized = bool(meta.get(AGG_FINALIZED_KEY))
    in_progress = bool(meta.get(AGG_IN_PROGRESS_KEY)) and not finalized

    if finalized:
        outcome = str(meta.get(AGG_OUTCOME_KEY) or meta.get("limited_time_outcome") or "")
        if outcome in {"success", "partial_success"}:
            status = "success"
        elif outcome == "failed":
            status = "failed"
        else:
            status = "success" if accumulated else "failed"
        detail = str(meta.get("limited_time_success_detail") or "")
        if outcome == "partial_success":
            detail = str(meta.get("limited_time_skip_reason") or detail)
        if not detail:
            detail = f"跨批限时限量购完成，累计成功 {accumulated} 个商品"
        return {
            "status": status,
            "detail": detail,
            "outcome": outcome or ("success" if accumulated else "failed"),
        }

    if in_progress or batch_log:
        done = len(batch_log)
        detail = f"分批限时限量购进行中（{done}/{total_batches or done} 批已记录"
        if accumulated:
            detail += f"，累计成功 {accumulated} 个商品"
        detail += "）"
        from pdd_agent.api.services.pipeline_per_batch_lt_chunks.bridge import (
            resolve_limited_time_step_chunk_hint,
        )

        chunk_hint = resolve_limited_time_step_chunk_hint(row)
        if chunk_hint:
            detail = chunk_hint
        return {
            "status": "running",
            "detail": detail,
            "outcome": "",
        }
    return None


def _campaign_activity_index(row) -> int:
    return max(0, int((row.meta or {}).get("campaign_activity_index") or 0))


def _resolve_activity_target_pdd_ids(row) -> list[str]:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        resolve_activity_product_ids_for_row,
    )

    pdd_ids, _mapping_ids = resolve_activity_product_ids_for_row(row)
    if pdd_ids:
        return list(pdd_ids)
    meta = dict(row.meta or {})
    accumulated = _accumulated_pdd_ids(meta)
    if accumulated:
        return accumulated
    return list(row.pdd_product_ids or [])


def record_campaign_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> None:
    """原始整合链路：活动报名完成后写入每商品 activity 状态。"""
    if not is_standard_per_batch_lt_pipeline(row):
        return
    if str((row.meta or {}).get("limited_time_run_id") or "").strip() == str(run_id or "").strip():
        return

    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
        record_activity_for_pipeline,
    )

    activity_ids = _pipeline_activity_ids(row)
    activity_index = _campaign_activity_index(row)
    current_activity_id = (
        activity_ids[activity_index] if activity_index < len(activity_ids) else str(row.activity_id or "")
    )
    if activity_index not in {0, 1}:
        return

    from pdd_agent.api.services.pipeline_service import _should_skip_campaign_for_traffic

    activity_skipped = (not success) and _should_skip_campaign_for_traffic(result, error)
    activity_continue = (
        (not success)
        and not activity_skipped
        and bool((row.meta or {}).get("continue_after_activity_failure"))
    )
    target_pdd_ids = _resolve_activity_target_pdd_ids(row)

    record_activity_for_pipeline(
        pipeline_id=row.pipeline_id,
        activity_index=activity_index,
        activity_id=current_activity_id,
        target_pdd_ids=target_pdd_ids,
        success=bool(success),
        skipped=activity_skipped,
        error=error or "活动报名失败",
    )
    logger.info(
        "pipeline %s std per-batch LT aggregate recorded activity index=%s activity_id=%s "
        "success=%s skipped=%s targets=%s run_id=%s continue=%s",
        row.pipeline_id,
        activity_index,
        current_activity_id,
        success,
        activity_skipped,
        len(target_pdd_ids),
        run_id,
        activity_continue,
    )


def record_traffic_finished(
    row,
    *,
    run_id: str,
    success: bool,
    error: str,
    result: dict[str, Any] | None = None,
) -> None:
    """原始整合链路：推广完成后写入每商品 promotion 状态。"""
    if not is_standard_per_batch_lt_pipeline(row):
        return
    if str(row.traffic_run_id or "").strip() != str(run_id or "").strip():
        return

    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
        record_promotion_for_pipeline,
    )
    from pdd_agent.storage import TaskRunStore

    if result is None:
        record = TaskRunStore().load(str(run_id or "").strip())
        result = dict(record.result or {}) if record else {}

    target_pdd_ids = _resolve_activity_target_pdd_ids(row)
    skipped = not bool(row.auto_promotion)
    record_promotion_for_pipeline(
        pipeline_id=row.pipeline_id,
        target_pdd_ids=target_pdd_ids,
        success=bool(success),
        skipped=skipped,
        error=error or "推广创建失败",
    )
    logger.info(
        "pipeline %s std per-batch LT aggregate recorded promotion success=%s skipped=%s targets=%s run_id=%s",
        row.pipeline_id,
        success,
        skipped,
        len(target_pdd_ids),
        run_id,
    )

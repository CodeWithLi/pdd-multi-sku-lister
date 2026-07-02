"""
可选策略：分批每批限时 + 仅限时成功报活动 — 跨批累计限时成功商品。

每批限时结束后，将本批 activity_created 成功的商品 ID 写入 meta 累计池；
最后一批结束时，合并「历史累计 + 本批」决定活动/推广用 ID。

效果：最后一批限时整单失败，但前面批次有限时成功时，仍会用累计成功的商品报活动。

回滚方式：
  1. 删除 pipeline_service._on_limited_time_finished 内对本模块的两处引用；或
  2. 链路 meta 设置 pipeline_lt_accumulate_success_for_activity_enabled=false。
"""

from __future__ import annotations

from typing import Any, Callable

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, update_integrated_pipeline

logger = get_logger(__name__)

POLICY_META_FLAG = "pipeline_lt_accumulate_success_for_activity_enabled"
ACCUMULATED_PDD_IDS_KEY = "accumulated_limited_time_success_pdd_product_ids"
ACCUMULATED_MAPPING_IDS_KEY = "accumulated_limited_time_success_mapping_ids"
ACCUMULATED_BATCH_COUNT_KEY = "accumulated_limited_time_success_batch_count"


def is_policy_enabled(row) -> bool:
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    if POLICY_META_FLAG in meta:
        return bool(meta[POLICY_META_FLAG])
    return True


def _policy_applies(row) -> bool:
    if not row or not is_policy_enabled(row):
        return False
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        is_activity_limited_time_success_only_row,
    )
    from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
        is_per_batch_limited_time_pipeline,
    )

    return is_activity_limited_time_success_only_row(row) and is_per_batch_limited_time_pipeline(row)


def _accumulated_pdd_ids(meta: dict[str, Any]) -> list[str]:
    raw = meta.get(ACCUMULATED_PDD_IDS_KEY) or []
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))


def _accumulated_mapping_ids(meta: dict[str, Any]) -> list[str]:
    raw = meta.get(ACCUMULATED_MAPPING_IDS_KEY) or []
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))


def _is_final_per_batch_limited_time_batch(row) -> bool:
    from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
        has_pending_throttled_listing_batches,
    )
    from pdd_agent.api.services.pipeline_per_batch_limited_time import _per_batch_state

    state = dict(_per_batch_state(row))
    if state.get("awaiting_final_activity"):
        return True
    return not has_pending_throttled_listing_batches(row)


def _extract_current_batch_success(
    row,
    *,
    run_id: str,
    result: dict[str, Any] | None,
):
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        extract_limited_time_success_products,
        load_limited_time_run_result,
    )

    payload = result if isinstance(result, dict) else load_limited_time_run_result(run_id)
    return extract_limited_time_success_products(
        payload,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=list(row.pdd_product_ids or []),
        fallback_mapping_ids=list(row.mapping_ids or []),
    )


def _merge_unique_pdd_ids(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            pid = str(item or "").strip()
            if pid and pid not in seen:
                seen.add(pid)
                merged.append(pid)
    return merged


def accumulate_per_batch_limited_time_success(
    row,
    *,
    run_id: str,
    result: dict[str, Any] | None,
):
    """
    每批限时结束后调用：将本批限时成功商品并入 meta 累计池。

    返回刷新后的 pipeline row（无变更则返回原 row）。
    """
    if not _policy_applies(row):
        return row

    extract = _extract_current_batch_success(row, run_id=run_id, result=result)
    if not extract.pdd_product_ids:
        return row

    meta = dict(row.meta or {})
    merged_pdd = _merge_unique_pdd_ids(_accumulated_pdd_ids(meta), extract.pdd_product_ids)
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        resolve_mapping_ids_for_pdd_products,
    )

    merged_mapping = resolve_mapping_ids_for_pdd_products(
        str(row.account_id or ""),
        merged_pdd,
        fallback_mapping_ids=_merge_unique_pdd_ids(
            _accumulated_mapping_ids(meta),
            extract.mapping_ids,
        ),
    )
    batch_count = int(meta.get(ACCUMULATED_BATCH_COUNT_KEY) or 0) + 1
    meta_patch = {
        ACCUMULATED_PDD_IDS_KEY: merged_pdd,
        ACCUMULATED_MAPPING_IDS_KEY: merged_mapping,
        ACCUMULATED_BATCH_COUNT_KEY: batch_count,
        "accumulated_limited_time_success_detail": (
            f"已累计 {len(merged_pdd)} 个限时成功商品（{batch_count} 批贡献）"
        ),
    }
    update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)
    logger.info(
        "pipeline %s accumulated limited time success batch=%s added=%s total=%s run_id=%s",
        row.pipeline_id,
        batch_count,
        len(extract.pdd_product_ids),
        len(merged_pdd),
        run_id,
    )
    return get_integrated_pipeline(row.pipeline_id) or row


def _build_merged_activity_products(row, *, run_id: str, result: dict[str, Any] | None):
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        LimitedTimeSuccessProducts,
        resolve_mapping_ids_for_pdd_products,
    )

    meta = dict(row.meta or {})
    current = _extract_current_batch_success(row, run_id=run_id, result=result)
    merged_pdd = _merge_unique_pdd_ids(_accumulated_pdd_ids(meta), current.pdd_product_ids)
    if not merged_pdd:
        return LimitedTimeSuccessProducts(pdd_product_ids=[], mapping_ids=[], source="none", detail="")

    merged_mapping = resolve_mapping_ids_for_pdd_products(
        str(row.account_id or ""),
        merged_pdd,
        fallback_mapping_ids=_merge_unique_pdd_ids(
            _accumulated_mapping_ids(meta),
            current.mapping_ids,
        ),
    )
    accumulated_only = len(_accumulated_pdd_ids(meta))
    current_only = len(current.pdd_product_ids)
    if accumulated_only and current_only:
        detail = (
            f"跨批累计限时成功 {len(merged_pdd)} 个商品"
            f"（历史 {accumulated_only} + 本批 {current_only}）"
        )
    elif accumulated_only:
        detail = f"跨批累计限时成功 {len(merged_pdd)} 个商品（本批无成功，使用历史累计）"
    else:
        detail = f"限时限量购成功 {len(merged_pdd)} 个商品"
    return LimitedTimeSuccessProducts(
        pdd_product_ids=merged_pdd,
        mapping_ids=merged_mapping,
        source="accumulated_limited_time_success",
        detail=detail,
    )


def maybe_finalize_limited_time_success_only_with_accumulation(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
    schedule_activity_fn: Callable[..., None],
    advance_store_sequential_fn: Callable[[Any], None],
) -> bool:
    """
    最后一批限时结束后：用「历史累计 + 本批」合并结果预约活动。

    若合并后仍无商品，返回 False，交由原 success_only 模块处理。
    """
    if not _policy_applies(row):
        return False
    if not _is_final_per_batch_limited_time_batch(row):
        return False

    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        build_limited_time_success_meta_patch,
    )

    merged = _build_merged_activity_products(row, run_id=run_id, result=result)
    if not merged.pdd_product_ids:
        return False

    from pdd_agent.storage import TaskRunStore

    record = TaskRunStore().load(str(run_id or "").strip())
    summarize = str(record.message or "") if record else ""

    meta_patch: dict[str, Any] = {
        "limited_time_finish_handled": True,
        "limited_time_summary": summarize,
    }
    meta_patch.update(build_limited_time_success_meta_patch(merged))
    meta_patch[ACCUMULATED_PDD_IDS_KEY] = list(merged.pdd_product_ids)
    meta_patch[ACCUMULATED_MAPPING_IDS_KEY] = list(merged.mapping_ids)

    if success and not error:
        meta_patch["limited_time_outcome"] = "success"
    else:
        meta_patch["limited_time_outcome"] = "partial_success"
        meta_patch["limited_time_skip_reason"] = (
            error or "最后一批限时限量购失败，使用历史累计成功商品继续活动"
        )

    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="limited_time_success_continue",
        pdd_product_ids=merged.pdd_product_ids,
        mapping_ids=merged.mapping_ids,
        error="",
        meta_patch=meta_patch,
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    schedule_activity_fn(
        refreshed,
        meta_patch=meta_patch,
        pdd_ids=merged.pdd_product_ids,
        mapping_ids=merged.mapping_ids,
    )
    logger.info(
        "pipeline %s accumulated limited time finalize activity pdd_ids=%s (%s)",
        row.pipeline_id,
        merged.pdd_product_ids,
        merged.detail,
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    advance_store_sequential_fn(refreshed)
    return True

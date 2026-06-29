"""
整合链路 — 分批上架后每批单独跑限时限量购。

开启后：每批上架完成 → 限时限量购（仅本批商品）→ 间隔后再入队下一批上架；
全部批次完成后才进入活动 / 推广（不再对全量商品重复跑限时限量购）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.api.services.pipeline_listing_throttle import (
    enqueue_listing_batch_for_pipeline,
    has_more_listing_batches,
    merge_throttle_accumulated_products,
)
from pdd_agent.api.services.task_runner import create_campaign_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import enqueue_task, get_integrated_pipeline, update_integrated_pipeline
from pdd_agent.domain.enums import AgentKind

logger = get_logger(__name__)

POST_LISTING_LIMITED_TIME_DELAY_SECONDS = 5
META_ENABLED_KEY = "listing_per_batch_limited_time_enabled"
META_STATE_KEY = "listing_per_batch_limited_time"


def per_batch_limited_time_meta_patch(*, enabled: bool) -> dict[str, Any]:
    """启动链路时写入 meta。"""
    if not enabled:
        return {}
    return {META_ENABLED_KEY: True}


def is_per_batch_limited_time_enabled(row) -> bool:
    meta = dict(row.meta or {})
    return bool(meta.get(META_ENABLED_KEY))


def _throttle_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get("listing_throttle") or {})


def _per_batch_state(row) -> dict[str, Any]:
    return dict((row.meta or {}).get(META_STATE_KEY) or {})


def _should_handle(row) -> bool:
    if not is_per_batch_limited_time_enabled(row):
        return False
    throttle = _throttle_state(row)
    if not throttle.get("enabled"):
        return False
    return int(throttle.get("total_batches") or 0) > 1


def _pipeline_auto_limited_time(row) -> bool:
    return bool((row.meta or {}).get("auto_limited_time_setup"))


def _pipeline_continue_after_limited_time_failure(row) -> bool:
    return bool((row.meta or {}).get("continue_after_limited_time_failure"))


def _enqueue_limited_time_for_batch(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    meta_patch: dict[str, Any],
    scheduled_at: datetime,
) -> str:
    limited_time_run_id = create_campaign_run(row.account_id)
    enqueue_task(
        agent=AgentKind.CAMPAIGN.value,
        run_id=limited_time_run_id,
        account_id=row.account_id,
        payload={
            "pipeline_id": row.pipeline_id,
            "campaign_type": "limited_time_setup",
            "pdd_product_ids": list(pdd_ids),
            "published_mapping_ids": list(mapping_ids),
        },
        scheduled_at=scheduled_at,
    )
    patch = dict(meta_patch or {})
    patch["limited_time_run_id"] = limited_time_run_id
    patch.pop("limited_time_finish_handled", None)
    is_future = scheduled_at > datetime.now()
    update_integrated_pipeline(
        row.pipeline_id,
        status="waiting_limited_time" if is_future else "running",
        current_step="waiting_limited_time_per_batch",
        pdd_product_ids=list(pdd_ids),
        mapping_ids=list(mapping_ids),
        error="",
        meta_patch=patch,
    )
    return limited_time_run_id


def maybe_run_per_batch_limited_time_after_listing(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_meta: dict[str, Any] | None = None,
) -> bool:
    """
    上架批次完成后调用。若已处理（入队本批限时限量购）返回 True，否则 False。
    """
    if not _should_handle(row):
        return False
    if not _pipeline_auto_limited_time(row):
        return False

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

    meta_patch[META_STATE_KEY] = per_batch_patch

    limited_time_at = datetime.now() + timedelta(seconds=POST_LISTING_LIMITED_TIME_DELAY_SECONDS)
    run_id = _enqueue_limited_time_for_batch(
        row,
        pdd_ids=list(pdd_ids),
        mapping_ids=list(mapping_ids),
        meta_patch=meta_patch,
        scheduled_at=limited_time_at,
    )
    logger.info(
        "pipeline %s per-batch limited time queued batch=%s/%s run_id=%s pdd_ids=%s more_batches=%s",
        row.pipeline_id,
        batch_index + 1,
        throttle.get("total_batches"),
        run_id,
        pdd_ids,
        more_batches,
    )
    return True


def maybe_continue_after_per_batch_limited_time(
    row,
    *,
    run_id: str,
    success: bool,
    error: str = "",
) -> bool:
    """
    限时限量购完成后调用。若本模块已接管后续（入队下一批上架或失败收尾）返回 True。
    """
    if not _should_handle(row):
        return False

    current_lt_run_id = str((row.meta or {}).get("limited_time_run_id") or "").strip()
    if current_lt_run_id != str(run_id or "").strip():
        return False

    state = _per_batch_state(row)
    if not state.get("enabled"):
        return False
    if state.get("awaiting_final_activity"):
        return False

    from pdd_agent.api.services.pipeline_per_batch_campaign import is_per_batch_campaign_enabled

    if is_per_batch_campaign_enabled(row):
        return False

    pending = dict(state.get("pending") or {})
    if not pending:
        return False

    failure_message = error or "限时限量购设置失败"
    lt_failure_meta: dict[str, Any] = {
        "limited_time_outcome": "failed",
        "limited_time_finish_handled": True,
        "per_batch_limited_time_last_error": failure_message,
    }
    if not success and not pending:
        if not _pipeline_continue_after_limited_time_failure(row):
            update_integrated_pipeline(
                row.pipeline_id,
                status="failed",
                current_step="limited_time_failed",
                error=failure_message,
                meta_patch=lt_failure_meta,
            )
            logger.info(
                "pipeline %s per-batch limited time failed at final batch=%s: %s",
                row.pipeline_id,
                int(state.get("last_batch_index") or 0) + 1,
                failure_message,
            )
            return True
        return False

    if not success:
        logger.warning(
            "pipeline %s per-batch limited time failed at batch=%s: %s; continuing to next listing batch",
            row.pipeline_id,
            int(state.get("last_batch_index") or 0) + 1,
            failure_message,
        )
        update_integrated_pipeline(
            row.pipeline_id,
            status="running",
            current_step="waiting_limited_time_per_batch",
            error="",
            meta_patch=lt_failure_meta,
        )

    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    throttle = _throttle_state(refreshed)
    batches = list(throttle.get("batches") or [])
    next_index = int(pending.get("next_batch_index") or 0)
    if next_index < 0 or next_index >= len(batches):
        logger.warning(
            "pipeline %s per-batch limited time pending batch index out of range: %s",
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
    # 下一批上架必须在「本批限时限量购完成之后」再等待 interval，不能在上批上架结束时提前计时。
    scheduled_at = datetime.now() + timedelta(minutes=interval_minutes)

    payload_base = dict(throttle.get("listing_payload_base") or {})
    meta_patch: dict[str, Any] = {
        META_STATE_KEY: {
            **state,
            "pending": None,
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
        "pipeline %s per-batch limited time done, next listing batch %s/%s scheduled at %s",
        refreshed.pipeline_id,
        next_index + 1,
        len(batches),
        scheduled_at,
    )
    return True


def resolve_activity_products_after_per_batch_listing(row, pdd_ids: list[str], mapping_ids: list[str]) -> tuple[list[str], list[str]]:
    """全部批次 + 分批限时限量购完成后，活动/推广应使用累计商品 ID。"""
    if not is_per_batch_limited_time_enabled(row):
        return pdd_ids, mapping_ids
    throttle = _throttle_state(row)
    if not throttle.get("enabled"):
        return pdd_ids, mapping_ids
    return merge_throttle_accumulated_products(throttle, pdd_ids=pdd_ids, mapping_ids=mapping_ids)


def prepare_pipeline_row_for_post_listing_steps(row):
    """最后一次分批限时限量购完成后，把累计商品 ID 写回 pipeline 供活动/推广使用。"""
    if not is_per_batch_limited_time_enabled(row):
        return row
    state = _per_batch_state(row)
    if not state.get("awaiting_final_activity"):
        return row
    throttle = _throttle_state(row)
    merged_pdd = list(throttle.get("accumulated_pdd_ids") or [])
    merged_map = list(throttle.get("accumulated_mapping_ids") or [])
    if not merged_pdd and not merged_map:
        return row
    update_integrated_pipeline(
        row.pipeline_id,
        pdd_product_ids=merged_pdd or None,
        mapping_ids=merged_map or None,
    )
    return get_integrated_pipeline(row.pipeline_id) or row

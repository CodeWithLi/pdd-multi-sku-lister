"""整合链路 — 多店铺串行执行（一家跑完再跑下一家，失败不阻断后续店铺）。"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, list_integrated_pipelines, update_integrated_pipeline

logger = get_logger(__name__)

STORE_SEQUENTIAL_META_KEY = "store_sequential"
LISTING_LIMITED_TIME_PHASE_KEY = "listing_limited_time_phase_completed"
STORE_SEQUENTIAL_ADVANCE_TRIGGERED_KEY = "store_sequential_advance_triggered"
TERMINAL_PIPELINE_STATUSES = frozenset({"completed", "failed", "canceled"})


def _call_start_integrated_pipeline(**kwargs: Any) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_service import start_integrated_pipeline

    return start_integrated_pipeline(**kwargs)


def build_store_sequential_common_params(
    *,
    activity_id: str,
    activity_ids: list[str],
    category_keyword: str,
    auto_promotion: bool,
    auto_limited_time_setup: bool,
    continue_after_limited_time_failure: bool,
    continue_after_activity_failure: bool,
    activity_delay_hours: float,
    demo_mode: bool,
    platform_listing_code: str,
    slot_alignment_test: bool,
    category_next_burst_demo: bool = True,
    skip_listing: bool,
    listing_skip_selectors: list[str] | None,
    material_source: str,
    relist_strategy: str,
    listing_throttle_enabled: bool,
    listing_batch_set_count: int,
    listing_batch_interval_minutes: int,
    listing_per_batch_limited_time_enabled: bool,
    listing_per_batch_campaign_enabled: bool,
    delist_spec_code_search_enabled: bool = False,
) -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "activity_ids": list(activity_ids),
        "category_keyword": category_keyword,
        "auto_promotion": auto_promotion,
        "auto_limited_time_setup": auto_limited_time_setup,
        "continue_after_limited_time_failure": continue_after_limited_time_failure,
        "continue_after_activity_failure": continue_after_activity_failure,
        "activity_delay_hours": activity_delay_hours,
        "demo_mode": demo_mode,
        "platform_listing_code": platform_listing_code,
        "slot_alignment_test": slot_alignment_test,
        "category_next_burst_demo": category_next_burst_demo,
        "skip_listing": skip_listing,
        "listing_skip_selectors": list(listing_skip_selectors or []),
        "material_source": material_source,
        "relist_strategy": relist_strategy,
        "listing_throttle_enabled": listing_throttle_enabled,
        "listing_batch_set_count": listing_batch_set_count,
        "listing_batch_interval_minutes": listing_batch_interval_minutes,
        "listing_per_batch_limited_time_enabled": listing_per_batch_limited_time_enabled,
        "listing_per_batch_campaign_enabled": listing_per_batch_campaign_enabled,
        "delist_spec_code_search_enabled": bool(delist_spec_code_search_enabled),
    }


def build_coordinator_sequential_meta(
    *,
    pending_items: list[dict[str, Any]],
    common_params: dict[str, Any],
    delay_min_seconds: int,
    delay_max_seconds: int,
    total_stores: int,
    active_pipeline_id: str,
) -> dict[str, Any]:
    return {
        STORE_SEQUENTIAL_META_KEY: {
            "enabled": True,
            "is_coordinator": True,
            "active_pipeline_id": active_pipeline_id,
            "pending_items": list(pending_items),
            "started_pipeline_ids": [active_pipeline_id],
            "total_stores": total_stores,
            "common_params": dict(common_params),
            "delay_min_seconds": max(0, int(delay_min_seconds)),
            "delay_max_seconds": max(0, int(delay_max_seconds)),
            "completed": False,
        }
    }


def build_child_sequential_meta(*, coordinator_pipeline_id: str, store_index: int) -> dict[str, Any]:
    return {
        STORE_SEQUENTIAL_META_KEY: {
            "enabled": True,
            "coordinator_pipeline_id": coordinator_pipeline_id,
            "store_index": store_index,
        }
    }


def _sequential_state(meta: dict[str, Any] | None) -> dict[str, Any]:
    raw = (meta or {}).get(STORE_SEQUENTIAL_META_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _resolve_coordinator_pipeline_id(row) -> str:
    seq = _sequential_state(row.meta if isinstance(row.meta, dict) else {})
    if seq.get("is_coordinator"):
        return str(row.pipeline_id or "").strip()
    return str(seq.get("coordinator_pipeline_id") or "").strip()


def find_coordinator_pipeline(batch_id: str) -> Any | None:
    batch_id = str(batch_id or "").strip()
    if not batch_id:
        return None
    rows = list_integrated_pipelines(limit=200, offset=0, batch_id=batch_id)
    for row in rows:
        seq = _sequential_state(row.meta if isinstance(row.meta, dict) else {})
        if seq.get("enabled") and seq.get("is_coordinator"):
            return row
    return None


def _resolve_inter_store_delay_seconds(seq: dict[str, Any]) -> int:
    delay_min = max(0, int(seq.get("delay_min_seconds") or 0))
    delay_max = max(delay_min, int(seq.get("delay_max_seconds") or delay_min))
    if delay_max <= 0:
        return 0
    return random.randint(delay_min, delay_max)


def _should_attempt_sequential_advance(finished_row):
    """解析串行协调器；若当前 pipeline 不是 active 店铺则返回 None。"""
    if not finished_row:
        return None
    meta = finished_row.meta if isinstance(finished_row.meta, dict) else {}
    batch_id = str(meta.get("batch_id") or "").strip()
    if not batch_id:
        return None

    seq_on_row = _sequential_state(meta)
    if not seq_on_row.get("enabled"):
        return None

    coordinator_id = _resolve_coordinator_pipeline_id(finished_row)
    if not coordinator_id:
        coordinator = find_coordinator_pipeline(batch_id)
        coordinator_id = str(coordinator.pipeline_id or "").strip() if coordinator else ""
    if not coordinator_id:
        return None

    coordinator = get_integrated_pipeline(coordinator_id)
    if not coordinator:
        return None

    seq = _sequential_state(coordinator.meta if isinstance(coordinator.meta, dict) else {})
    if not seq.get("enabled") or not seq.get("is_coordinator"):
        return None
    if seq.get("completed"):
        return None

    active_pipeline_id = str(seq.get("active_pipeline_id") or "").strip()
    finished_pipeline_id = str(finished_row.pipeline_id or "").strip()
    if active_pipeline_id and active_pipeline_id != finished_pipeline_id:
        return None

    return coordinator_id, coordinator


def maybe_advance_sequential_store_after_listing_limited_time(row) -> dict[str, Any] | None:
    """
    当前店铺「上架 + 限时限量购」全部完成后启动下一家。

    活动/推广仍在后台按预约时间执行，不阻塞下一家店铺。
    """
    if not row:
        return None
    meta = row.meta if isinstance(row.meta, dict) else {}
    if meta.get(STORE_SEQUENTIAL_ADVANCE_TRIGGERED_KEY):
        return None

    resolved = _should_attempt_sequential_advance(row)
    if not resolved:
        return None
    coordinator_id, coordinator = resolved

    finished_pipeline_id = str(row.pipeline_id or "").strip()
    update_integrated_pipeline(
        finished_pipeline_id,
        meta_patch={
            LISTING_LIMITED_TIME_PHASE_KEY: True,
            STORE_SEQUENTIAL_ADVANCE_TRIGGERED_KEY: True,
        },
    )
    logger.info(
        "store sequential listing+limited-time phase done pipeline=%s coordinator=%s",
        finished_pipeline_id,
        coordinator_id,
    )
    return _start_next_store_from_coordinator(coordinator)


def maybe_advance_sequential_store(finished_row) -> dict[str, Any] | None:
    """
    当前店铺链路进入终态后，启动下一家店铺（成功/失败/取消均继续）。

    若已在「上架+限时限量购」阶段交接过下一家，则不再重复启动。

    返回新启动的 pipeline dict；无待启动店铺时返回 None。
    """
    if not finished_row:
        return None
    meta = finished_row.meta if isinstance(finished_row.meta, dict) else {}
    if meta.get(STORE_SEQUENTIAL_ADVANCE_TRIGGERED_KEY):
        return None

    if str(finished_row.status or "") not in TERMINAL_PIPELINE_STATUSES:
        return None

    resolved = _should_attempt_sequential_advance(finished_row)
    if not resolved:
        return None
    _, coordinator = resolved
    return _start_next_store_from_coordinator(coordinator)


def _start_next_store_from_coordinator(coordinator) -> dict[str, Any] | None:
    coordinator_id = str(coordinator.pipeline_id or "").strip()
    seq = _sequential_state(coordinator.meta if isinstance(coordinator.meta, dict) else {})
    batch_id = str((coordinator.meta or {}).get("batch_id") or "").strip()

    pending_items = list(seq.get("pending_items") or [])
    while pending_items:
        next_item = pending_items[0]
        pending_items = pending_items[1:]
        account_id = str(next_item.get("account_id") or "").strip()
        product_codes = list(next_item.get("product_codes") or [])
        if not account_id or not product_codes:
            logger.warning(
                "store sequential skip invalid pending item batch_id=%s account=%s",
                batch_id,
                account_id,
            )
            update_integrated_pipeline(
                coordinator_id,
                meta_patch={
                    STORE_SEQUENTIAL_META_KEY: {
                        **seq,
                        "pending_items": pending_items,
                    }
                },
            )
            seq = {**seq, "pending_items": pending_items}
            continue

        common_params = dict(seq.get("common_params") or {})
        delay_seconds = _resolve_inter_store_delay_seconds(seq)
        scheduled_at = datetime.now() + timedelta(seconds=delay_seconds)
        store_index = len(list(seq.get("started_pipeline_ids") or []))

        data = _call_start_integrated_pipeline(
            account_id=account_id,
            product_codes=product_codes,
            batch_id=batch_id,
            listing_scheduled_at=scheduled_at,
            extra_meta=build_child_sequential_meta(
                coordinator_pipeline_id=coordinator_id,
                store_index=store_index,
            ),
            **common_params,
        )
        new_pipeline_id = str(data.get("pipeline_id") or "").strip()
        started_ids = list(dict.fromkeys([*(seq.get("started_pipeline_ids") or []), new_pipeline_id]))
        update_integrated_pipeline(
            coordinator_id,
            meta_patch={
                STORE_SEQUENTIAL_META_KEY: {
                    **seq,
                    "active_pipeline_id": new_pipeline_id,
                    "pending_items": pending_items,
                    "started_pipeline_ids": started_ids,
                    "completed": not pending_items,
                }
            },
        )
        logger.info(
            "store sequential advanced batch_id=%s store=%s pipeline=%s delay=%ss remaining=%s relist=%s",
            batch_id,
            account_id,
            new_pipeline_id,
            delay_seconds,
            len(pending_items),
            str(common_params.get("relist_strategy") or "ignore"),
        )
        return data

    update_integrated_pipeline(
        coordinator_id,
        meta_patch={
            STORE_SEQUENTIAL_META_KEY: {
                **seq,
                "completed": True,
                "pending_items": [],
            }
        },
    )
    logger.info(
        "store sequential batch finished batch_id=%s coordinator=%s",
        batch_id,
        coordinator_id,
    )
    return None

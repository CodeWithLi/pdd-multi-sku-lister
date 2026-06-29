"""
整合链路 — 按套图分批上架（风控节流）。

将所选商品按「套图」分组，每批最多 N 套，批次之间间隔 M 分钟再入队下一批上架。
全部批次完成后才进入限时限量购 / 活动 / 推广。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pdd_agent.api.services.task_runner import create_listing_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import enqueue_task, get_integrated_pipeline, update_integrated_pipeline
from pdd_agent.domain.enums import AgentKind

logger = get_logger(__name__)


def image_set_key_from_selector(selector: str) -> str:
    """BD713/第一套图/BD713A → BD713/第一套图；BD713/第一套图 → BD713/第一套图。"""
    parts = [part.strip() for part in str(selector or "").split("/") if part.strip()]
    if len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}"
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if parts else str(selector or "").strip()


def group_selectors_by_image_set(selectors: list[str]) -> list[tuple[str, list[str]]]:
    """按套图分组并保持套图顺序。"""
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for raw in selectors:
        selector = str(raw or "").strip()
        if not selector:
            continue
        key = image_set_key_from_selector(selector)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(selector)
    return [(key, groups[key]) for key in order]


def split_selectors_into_set_batches(
    selectors: list[str],
    *,
    batch_set_count: int,
) -> list[list[str]]:
    """按套图数量切分 selector 列表。"""
    count = max(1, int(batch_set_count or 1))
    set_groups = group_selectors_by_image_set(selectors)
    if len(set_groups) <= count:
        return [selectors] if selectors else []

    batches: list[list[str]] = []
    current: list[str] = []
    sets_in_batch = 0
    for _key, group_selectors in set_groups:
        if sets_in_batch >= count and current:
            batches.append(current)
            current = []
            sets_in_batch = 0
        current.extend(group_selectors)
        sets_in_batch += 1
    if current:
        batches.append(current)
    return batches


def build_listing_throttle_state(
    selectors: list[str],
    *,
    enabled: bool,
    batch_set_count: int,
    interval_minutes: int,
    listing_payload_base: dict[str, Any],
) -> dict[str, Any] | None:
    """生成分批上架 meta；仅 1 批或未启用时返回 None。"""
    if not enabled:
        return None
    codes = list(dict.fromkeys(str(s).strip() for s in selectors if str(s).strip()))
    if not codes:
        return None

    batches = split_selectors_into_set_batches(codes, batch_set_count=batch_set_count)
    if len(batches) <= 1:
        return None

    set_groups = group_selectors_by_image_set(codes)
    return {
        "enabled": True,
        "batch_set_count": max(1, int(batch_set_count or 1)),
        "interval_minutes": max(1, int(interval_minutes or 1)),
        "total_sets": len(set_groups),
        "total_batches": len(batches),
        "batches": batches,
        "batch_index": 0,
        "accumulated_pdd_ids": [],
        "accumulated_mapping_ids": [],
        "listing_payload_base": dict(listing_payload_base or {}),
    }


def apply_throttle_to_listing_codes(
    selectors: list[str],
    throttle_state: dict[str, Any] | None,
) -> list[str]:
    if not throttle_state or not throttle_state.get("enabled"):
        return list(selectors)
    batches = list(throttle_state.get("batches") or [])
    if not batches:
        return list(selectors)
    batch_index = int(throttle_state.get("batch_index") or 0)
    if batch_index < 0 or batch_index >= len(batches):
        batch_index = 0
    return list(batches[batch_index])


def throttle_listing_detail(throttle_state: dict[str, Any] | None) -> str:
    if not throttle_state or not throttle_state.get("enabled"):
        return ""
    batch_index = int(throttle_state.get("batch_index") or 0) + 1
    total = int(throttle_state.get("total_batches") or 0)
    interval = int(throttle_state.get("interval_minutes") or 0)
    per_batch = int(throttle_state.get("batch_set_count") or 0)
    return f"分批上架 {batch_index}/{total}（每批 {per_batch} 套，间隔 {interval} 分钟）"


def merge_throttle_accumulated_products(
    throttle_state: dict[str, Any],
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
) -> tuple[list[str], list[str]]:
    acc_pdd = list(throttle_state.get("accumulated_pdd_ids") or [])
    acc_map = list(throttle_state.get("accumulated_mapping_ids") or [])
    merged_pdd = list(dict.fromkeys([*acc_pdd, *(pdd_ids or [])]))
    merged_map = list(dict.fromkeys([*acc_map, *(mapping_ids or [])]))
    return merged_pdd, merged_map


def has_more_listing_batches(throttle_state: dict[str, Any]) -> bool:
    batches = list(throttle_state.get("batches") or [])
    batch_index = int(throttle_state.get("batch_index") or 0)
    return bool(batches) and batch_index + 1 < len(batches)


def enqueue_listing_batch_for_pipeline(
    *,
    pipeline_id: str,
    account_id: str,
    batch_codes: list[str],
    listing_payload_base: dict[str, Any],
    scheduled_at: datetime | None = None,
    update_listing_run_id: bool = True,
) -> str:
    """入队单批上架任务，返回 run_id。"""
    run_id = create_listing_run(account_id)
    payload_base = dict(listing_payload_base or {})
    enqueue_task(
        agent=AgentKind.LISTING.value,
        run_id=run_id,
        account_id=account_id,
        payload={
            "product_codes": list(batch_codes),
            "dry_run": False,
            "category_keyword": str(payload_base.get("category_keyword") or "玩偶"),
            "platform_listing_code": str(payload_base.get("platform_listing_code") or ""),
            "pipeline_id": pipeline_id,
            "slot_alignment_test": bool(payload_base.get("slot_alignment_test")),
            "category_next_burst_demo": bool(payload_base.get("category_next_burst_demo", True)),
            "material_source": str(payload_base.get("material_source") or ""),
        },
        scheduled_at=scheduled_at or datetime.now(),
    )
    patch: dict[str, Any] = {
        "current_step": "listing_queued",
    }
    if update_listing_run_id:
        update_integrated_pipeline(pipeline_id, listing_run_id=run_id, meta_patch=patch)
    else:
        update_integrated_pipeline(pipeline_id, meta_patch=patch)
    logger.info(
        "pipeline listing batch queued pipeline_id=%s run_id=%s products=%s at=%s",
        pipeline_id,
        run_id,
        len(batch_codes),
        scheduled_at or datetime.now(),
    )
    return run_id


def schedule_next_listing_batch_after_finish(
    row,
    *,
    pdd_ids: list[str],
    mapping_ids: list[str],
    listing_meta: dict[str, Any] | None = None,
) -> bool:
    """
    当前批次上架完成后调用。

    若还有下一批：累计商品 ID、预约下一批上架，返回 True（链路暂不进入活动）。
    若已是最后一批：写回累计 ID 到 meta，返回 False（由调用方继续后续步骤）。
    """
    meta = dict(row.meta or {})
    throttle = dict(meta.get("listing_throttle") or {})
    if not throttle.get("enabled"):
        return False

    merged_pdd, merged_map = merge_throttle_accumulated_products(
        throttle,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
    )
    batch_index = int(throttle.get("batch_index") or 0)
    batches = list(throttle.get("batches") or [])
    next_index = batch_index + 1

    meta_patch = dict(listing_meta or {})
    meta_patch["listing_throttle"] = {
        **throttle,
        "accumulated_pdd_ids": merged_pdd,
        "accumulated_mapping_ids": merged_map,
    }

    if next_index >= len(batches):
        meta_patch["listing_throttle"]["batch_index"] = batch_index
        meta_patch["listing_throttle"]["completed"] = True
        update_integrated_pipeline(row.pipeline_id, meta_patch=meta_patch)
        return False

    interval_minutes = max(1, int(throttle.get("interval_minutes") or 1))
    scheduled_at = datetime.now() + timedelta(minutes=interval_minutes)
    payload_base = dict(throttle.get("listing_payload_base") or {})

    meta_patch["listing_throttle"]["batch_index"] = next_index
    meta_patch["listing_throttle"]["next_batch_scheduled_at"] = scheduled_at.isoformat(
        timespec="seconds"
    )
    update_integrated_pipeline(
        row.pipeline_id,
        current_step=f"waiting_listing_batch_{next_index + 1}",
        meta_patch=meta_patch,
    )

    enqueue_listing_batch_for_pipeline(
        pipeline_id=row.pipeline_id,
        account_id=row.account_id,
        batch_codes=list(batches[next_index]),
        listing_payload_base=payload_base,
        scheduled_at=scheduled_at,
    )
    logger.info(
        "pipeline %s scheduled listing batch %s/%s at %s",
        row.pipeline_id,
        next_index + 1,
        len(batches),
        scheduled_at,
    )
    return True


def resolve_listing_products_after_batches(row, pdd_ids: list[str], mapping_ids: list[str]) -> tuple[list[str], list[str]]:
    """全部批次完成后，合并累计与当前批次的商品 ID。"""
    meta = dict(row.meta or {})
    throttle = dict(meta.get("listing_throttle") or {})
    if not throttle.get("enabled"):
        return pdd_ids, mapping_ids
    return merge_throttle_accumulated_products(throttle, pdd_ids=pdd_ids, mapping_ids=mapping_ids)


def patch_pending_listing_with_throttle(
    pending_listing: dict[str, Any],
    throttle_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """relist prep 完成后 pending_listing 仍保留全量 codes；throttle 在 pipeline meta 中。"""
    pending = dict(pending_listing or {})
    if throttle_state:
        pending["listing_throttle_enabled"] = True
    return pending

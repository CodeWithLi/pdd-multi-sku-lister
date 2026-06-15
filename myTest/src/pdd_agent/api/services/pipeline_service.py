"""上架 → 活动 → 推广 整合链路。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from pdd_agent.api.services.task_runner import create_campaign_run, create_listing_run, create_traffic_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    create_integrated_pipeline,
    enqueue_task,
    get_integrated_pipeline,
    list_integrated_pipelines,
    update_integrated_pipeline,
)
from pdd_agent.domain.enums import AgentKind, RunStatus
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)

DEMO_ACTIVITY_DELAY_MINUTES = 2


def _pipeline_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _resolve_activity_delay(*, demo_mode: bool, activity_delay_hours: float) -> timedelta:
    if demo_mode:
        return timedelta(minutes=DEMO_ACTIVITY_DELAY_MINUTES)
    hours = max(0.0, float(activity_delay_hours or 24.0))
    return timedelta(hours=hours)


def _extract_listing_products(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    pdd_ids: list[str] = []
    mapping_ids: list[str] = []
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") not in {"success", "completed", "listed"}:
            continue
        pid = str(item.get("pdd_product_id") or "").strip()
        if pid:
            pdd_ids.append(pid)
        mapping_id = str(item.get("mapping_id") or "").strip()
        if mapping_id:
            mapping_ids.append(mapping_id)
    return list(dict.fromkeys(pdd_ids)), list(dict.fromkeys(mapping_ids))


def _step_infos(row) -> list[dict[str, Any]]:
    listing_status = "pending"
    if row.listing_run_id:
        record = TaskRunStore().load(row.listing_run_id)
        if record:
            listing_status = str(record.status.value if hasattr(record.status, "value") else record.status)

    campaign_status = "pending"
    if row.current_step == "waiting_activity":
        campaign_status = "scheduled"
    elif row.campaign_run_id:
        record = TaskRunStore().load(row.campaign_run_id)
        if record:
            campaign_status = str(record.status.value if hasattr(record.status, "value") else record.status)

    traffic_status = "pending"
    if row.traffic_run_id:
        record = TaskRunStore().load(row.traffic_run_id)
        if record:
            traffic_status = str(record.status.value if hasattr(record.status, "value") else record.status)
    elif row.status == "completed" and row.auto_promotion:
        traffic_status = "skipped"
    elif row.status == "completed":
        traffic_status = "skipped"

    return [
        {
            "key": "listing",
            "label": "上架",
            "status": listing_status,
            "run_id": row.listing_run_id or "",
            "detail": "将素材上架到拼多多",
        },
        {
            "key": "activity",
            "label": "活动报名",
            "status": campaign_status,
            "run_id": row.campaign_run_id or "",
            "scheduled_at": row.scheduled_activity_at,
            "detail": (
                f"计划于 {row.scheduled_activity_at:%Y-%m-%d %H:%M} 自动报名"
                if row.scheduled_activity_at and campaign_status == "scheduled"
                else "等待上架完成后预约"
            ),
        },
        {
            "key": "traffic",
            "label": "推广",
            "status": traffic_status,
            "run_id": row.traffic_run_id or "",
            "detail": "活动报名成功后自动创建推广" if row.auto_promotion else "未启用",
        },
    ]


def pipeline_to_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "pipeline_id": row.pipeline_id,
        "account_id": row.account_id,
        "status": row.status,
        "current_step": row.current_step,
        "product_codes": list(row.product_codes or []),
        "activity_id": row.activity_id,
        "auto_promotion": bool(row.auto_promotion),
        "activity_delay_hours": float(row.activity_delay_hours or 24.0),
        "demo_mode": bool(row.demo_mode),
        "slot_alignment_test": bool((row.meta or {}).get("slot_alignment_test")),
        "listing_run_id": row.listing_run_id or "",
        "campaign_run_id": row.campaign_run_id or "",
        "traffic_run_id": row.traffic_run_id or "",
        "pdd_product_ids": list(row.pdd_product_ids or []),
        "mapping_ids": list(row.mapping_ids or []),
        "scheduled_activity_at": row.scheduled_activity_at,
        "error": row.error or "",
        "steps": _step_infos(row),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def start_integrated_pipeline(
    *,
    account_id: str,
    product_codes: list[str],
    activity_id: str,
    category_keyword: str = "玩偶",
    auto_promotion: bool = True,
    activity_delay_hours: float = 24.0,
    demo_mode: bool = False,
    platform_listing_code: str = "",
    slot_alignment_test: bool = False,
) -> dict[str, Any]:
    account_id = str(account_id or "").strip()
    activity_id = str(activity_id or "").strip()
    codes = list(dict.fromkeys(str(code).strip() for code in product_codes if str(code).strip()))
    if not account_id:
        raise ValueError("account_id is required")
    if not codes:
        raise ValueError("product_codes is required")
    if not activity_id:
        raise ValueError("activity_id is required")

    pipeline_id = _pipeline_id()
    listing_run_id = create_listing_run(account_id)
    row = create_integrated_pipeline(
        pipeline_id=pipeline_id,
        account_id=account_id,
        product_codes=codes,
        activity_id=activity_id,
        auto_promotion=auto_promotion,
        activity_delay_hours=activity_delay_hours,
        demo_mode=demo_mode,
        listing_run_id=listing_run_id,
        meta={
            "category_keyword": category_keyword,
            "platform_listing_code": platform_listing_code,
            "slot_alignment_test": bool(slot_alignment_test),
        },
    )
    enqueue_task(
        agent=AgentKind.LISTING.value,
        run_id=listing_run_id,
        account_id=account_id,
        payload={
            "product_codes": codes,
            "dry_run": False,
            "category_keyword": category_keyword,
            "platform_listing_code": platform_listing_code,
            "pipeline_id": pipeline_id,
            "slot_alignment_test": bool(slot_alignment_test),
        },
        scheduled_at=datetime.now(),
    )
    logger.info(
        "integrated pipeline started pipeline_id=%s account=%s activity=%s demo=%s",
        pipeline_id,
        account_id,
        activity_id,
        demo_mode,
    )
    refreshed = get_integrated_pipeline(pipeline_id)
    return pipeline_to_dict(refreshed or row)


def on_queue_task_finished(
    *,
    agent: str,
    pipeline_id: str,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id:
        return
    row = get_integrated_pipeline(pipeline_id)
    if not row:
        return

    result = result if isinstance(result, dict) else {}
    if agent == AgentKind.LISTING.value:
        _on_listing_finished(row, run_id=run_id, success=success, result=result, error=error)
    elif agent == AgentKind.CAMPAIGN.value:
        _on_campaign_finished(row, run_id=run_id, success=success, result=result, error=error)
    elif agent == AgentKind.TRAFFIC.value:
        _on_traffic_finished(row, run_id=run_id, success=success, error=error)


def _on_listing_finished(row, *, run_id: str, success: bool, result: dict[str, Any], error: str) -> None:
    if not success:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="listing_failed",
            error=error or "上架失败",
        )
        return

    pdd_ids, mapping_ids = _extract_listing_products(result)
    if not pdd_ids:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="listing_failed",
            error="上架完成但未获取到拼多多商品 ID",
        )
        return

    delay = _resolve_activity_delay(
        demo_mode=bool(row.demo_mode),
        activity_delay_hours=float(row.activity_delay_hours or 24.0),
    )
    scheduled_at = datetime.now() + delay
    campaign_run_id = create_campaign_run(row.account_id)
    enqueue_task(
        agent=AgentKind.CAMPAIGN.value,
        run_id=campaign_run_id,
        account_id=row.account_id,
        payload={
            "pipeline_id": row.pipeline_id,
            "campaign_type": "marketing_activity_register",
            "activity_id": row.activity_id,
            "pdd_product_ids": pdd_ids,
        },
        scheduled_at=scheduled_at,
    )
    update_integrated_pipeline(
        row.pipeline_id,
        status="waiting_activity",
        current_step="waiting_activity",
        pdd_product_ids=pdd_ids,
        mapping_ids=mapping_ids,
        campaign_run_id=campaign_run_id,
        scheduled_activity_at=scheduled_at,
        error="",
        meta_patch={
            "listing_summary": TaskRunStore().load(run_id).message if TaskRunStore().load(run_id) else "",
        },
    )
    logger.info(
        "pipeline %s listing done, activity scheduled at %s pdd_ids=%s",
        row.pipeline_id,
        scheduled_at,
        pdd_ids,
    )


def _on_campaign_finished(row, *, run_id: str, success: bool, result: dict[str, Any], error: str) -> None:
    if not success:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="activity_failed",
            error=error or "活动报名失败",
        )
        return

    if not row.auto_promotion:
        update_integrated_pipeline(
            row.pipeline_id,
            status="completed",
            current_step="completed",
            error="",
            meta_patch={"campaign_summary": _summarize_run_message(run_id)},
        )
        return

    pdd_ids = list(row.pdd_product_ids or [])
    mapping_ids = list(row.mapping_ids or [])
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
    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="traffic_queued",
        traffic_run_id=traffic_run_id,
        error="",
        meta_patch={"campaign_summary": _summarize_run_message(run_id)},
    )


def _on_traffic_finished(row, *, run_id: str, success: bool, error: str) -> None:
    if not success:
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="traffic_failed",
            error=error or "推广创建失败",
        )
        return
    update_integrated_pipeline(
        row.pipeline_id,
        status="completed",
        current_step="completed",
        error="",
        meta_patch={"traffic_summary": _summarize_run_message(run_id)},
    )


def _summarize_run_message(run_id: str) -> str:
    record = TaskRunStore().load(run_id)
    return str(record.message or "") if record else ""


def get_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    row = get_integrated_pipeline(pipeline_id)
    return pipeline_to_dict(row) if row else None


def list_pipelines(*, limit: int = 50) -> dict[str, Any]:
    rows = list_integrated_pipelines(limit=limit)
    items = [pipeline_to_dict(row) for row in rows]
    return {"items": items, "total": len(items)}

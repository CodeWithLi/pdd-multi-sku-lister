"""
整合链路分批模式 — 每批每商品阶段状态持久化。

独立于 pipeline_service / per_batch_* 模块，供 pipeline_per_batch_lt_traffic_activity 调用。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.models import IntegratedPipelineBatchProductStageORM
from pdd_agent.db.session import session_scope

logger = get_logger(__name__)

STAGE_PENDING = "pending"
STAGE_SUCCESS = "success"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"


def _new_record_id() -> str:
    return f"pbps_{uuid.uuid4().hex[:16]}"


def _normalize_selector(value: str) -> str:
    return str(value or "").strip()


def _listing_label_from_selector(selector: str) -> str:
    parts = [p.strip() for p in selector.split("/") if p.strip()]
    if len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}/{parts[2]}"
    return selector


def ensure_batch_product_rows(
    *,
    pipeline_id: str,
    account_id: str,
    batch_index: int,
    product_selectors: list[str],
    activity_ids: list[str] | None = None,
) -> None:
    """为本批商品初始化 tracker 行（幂等）。"""
    pipeline_id = str(pipeline_id or "").strip()
    account_id = str(account_id or "").strip()
    if not pipeline_id or not product_selectors:
        return

    activity_ids = list(dict.fromkeys(str(x).strip() for x in (activity_ids or []) if str(x).strip()))
    act1 = activity_ids[0] if len(activity_ids) > 0 else ""
    act2 = activity_ids[1] if len(activity_ids) > 1 else ""

    try:
        with session_scope() as session:
            for raw in product_selectors:
                selector = _normalize_selector(raw)
                if not selector:
                    continue
                existing = (
                    session.query(IntegratedPipelineBatchProductStageORM)
                    .filter_by(
                        pipeline_id=pipeline_id,
                        batch_index=int(batch_index),
                        product_selector=selector,
                    )
                    .first()
                )
                if existing:
                    if act1 and not existing.activity_1_id:
                        existing.activity_1_id = act1
                    if act2 and not existing.activity_2_id:
                        existing.activity_2_id = act2
                    continue
                session.add(
                    IntegratedPipelineBatchProductStageORM(
                        record_id=_new_record_id(),
                        pipeline_id=pipeline_id,
                        account_id=account_id,
                        batch_index=int(batch_index),
                        product_selector=selector,
                        listing_label=_listing_label_from_selector(selector),
                        activity_1_id=act1,
                        activity_2_id=act2,
                    )
                )
    except Exception:
        logger.exception(
            "ensure batch product stage rows failed pipeline_id=%s batch=%s",
            pipeline_id,
            batch_index,
        )


def _apply_listing_result_item(
    row: IntegratedPipelineBatchProductStageORM,
    item: dict[str, Any],
) -> None:
    status = str(item.get("status") or "").strip().lower()
    if status in {"skipped"}:
        row.listing_status = STAGE_SKIPPED
        row.listing_error = str(item.get("error") or item.get("reason") or "").strip()
        return
    if status in {"success", "completed", "listed"}:
        row.listing_status = STAGE_SUCCESS
        row.listing_error = ""
        pid = str(item.get("pdd_product_id") or "").strip()
        if pid:
            row.pdd_product_id = pid
        mapping_id = str(item.get("mapping_id") or "").strip()
        if mapping_id:
            row.mapping_id = mapping_id
        label = str(item.get("listing_label") or "").strip()
        if label:
            row.listing_label = label
        return
    row.listing_status = STAGE_FAILED
    row.listing_error = str(item.get("error") or item.get("reason") or item.get("message") or "上架失败").strip()


def record_listing_batch_from_result(
    *,
    pipeline_id: str,
    account_id: str,
    batch_index: int,
    batch_selectors: list[str],
    listing_result: dict[str, Any] | None,
    activity_ids: list[str] | None = None,
) -> None:
    ensure_batch_product_rows(
        pipeline_id=pipeline_id,
        account_id=account_id,
        batch_index=batch_index,
        product_selectors=batch_selectors,
        activity_ids=activity_ids,
    )
    items = [
        item
        for item in (listing_result or {}).get("results") or []
        if isinstance(item, dict)
    ]
    label_to_item: dict[str, dict[str, Any]] = {}
    selector_to_item: dict[str, dict[str, Any]] = {}
    for item in items:
        label = str(item.get("listing_label") or "").strip()
        if label:
            label_to_item[label] = item
        code = str(item.get("product_code") or item.get("platform_listing_code") or "").strip()
        if code:
            selector_to_item[code] = item

    try:
        with session_scope() as session:
            rows = (
                session.query(IntegratedPipelineBatchProductStageORM)
                .filter_by(pipeline_id=pipeline_id, batch_index=int(batch_index))
                .all()
            )
            for row in rows:
                item = label_to_item.get(row.listing_label) or selector_to_item.get(row.product_selector)
                if item:
                    _apply_listing_result_item(row, item)
                elif row.listing_status == STAGE_PENDING:
                    row.listing_status = STAGE_FAILED
                    row.listing_error = "本批上架结果中未找到该商品"
                row.updated_at = datetime.now()
    except Exception:
        logger.exception(
            "record listing batch stage failed pipeline_id=%s batch=%s",
            pipeline_id,
            batch_index,
        )


def _match_rows_for_pdd_ids(
    session,
    *,
    pipeline_id: str,
    batch_index: int | None,
    pdd_product_ids: list[str],
) -> list[IntegratedPipelineBatchProductStageORM]:
    pdd_set = {str(x).strip() for x in pdd_product_ids if str(x).strip()}
    if not pdd_set:
        return []
    query = session.query(IntegratedPipelineBatchProductStageORM).filter_by(pipeline_id=pipeline_id)
    if batch_index is not None:
        query = query.filter_by(batch_index=int(batch_index))
    rows = query.all()
    return [row for row in rows if str(row.pdd_product_id or "").strip() in pdd_set]


def record_limited_time_batch(
    *,
    pipeline_id: str,
    batch_index: int,
    success_pdd_ids: list[str],
    failed_pdd_ids: list[str] | None = None,
    batch_failed: bool = False,
    error: str = "",
) -> None:
    success_set = {str(x).strip() for x in success_pdd_ids if str(x).strip()}
    failed_set = {str(x).strip() for x in (failed_pdd_ids or []) if str(x).strip()}
    try:
        with session_scope() as session:
            rows = (
                session.query(IntegratedPipelineBatchProductStageORM)
                .filter_by(pipeline_id=pipeline_id, batch_index=int(batch_index))
                .all()
            )
            for row in rows:
                pid = str(row.pdd_product_id or "").strip()
                if not pid:
                    if batch_failed:
                        row.limited_time_status = STAGE_SKIPPED
                        row.limited_time_error = error or "上架未成功，跳过限时限量购"
                    continue
                if pid in success_set:
                    row.limited_time_status = STAGE_SUCCESS
                    row.limited_time_error = ""
                elif pid in failed_set or batch_failed:
                    row.limited_time_status = STAGE_FAILED
                    row.limited_time_error = error or "限时限量购失败"
                elif row.limited_time_status == STAGE_PENDING:
                    row.limited_time_status = STAGE_SKIPPED
                    row.limited_time_error = "本批限时限量购未包含该商品"
                row.updated_at = datetime.now()
    except Exception:
        logger.exception(
            "record limited time batch stage failed pipeline_id=%s batch=%s",
            pipeline_id,
            batch_index,
        )


def record_promotion_batch(
    *,
    pipeline_id: str,
    batch_index: int,
    target_pdd_ids: list[str],
    success: bool,
    skipped: bool = False,
    error: str = "",
) -> None:
    if skipped or not target_pdd_ids:
        status = STAGE_SKIPPED
        err = error or "无限时限量购成功商品，跳过推广"
    elif success:
        status = STAGE_SUCCESS
        err = ""
    else:
        status = STAGE_FAILED
        err = error or "推广创建失败"

    try:
        with session_scope() as session:
            rows = _match_rows_for_pdd_ids(
                session,
                pipeline_id=pipeline_id,
                batch_index=batch_index,
                pdd_product_ids=target_pdd_ids,
            )
            if not rows:
                rows = (
                    session.query(IntegratedPipelineBatchProductStageORM)
                    .filter_by(pipeline_id=pipeline_id, batch_index=int(batch_index))
                    .all()
                )
            for row in rows:
                pid = str(row.pdd_product_id or "").strip()
                if skipped or not target_pdd_ids:
                    if pid and pid not in set(target_pdd_ids):
                        continue
                    row.promotion_status = STAGE_SKIPPED
                    row.promotion_error = err
                elif pid and pid in set(target_pdd_ids):
                    row.promotion_status = status
                    row.promotion_error = err
                elif not target_pdd_ids:
                    row.promotion_status = status
                    row.promotion_error = err
                row.updated_at = datetime.now()
    except Exception:
        logger.exception(
            "record promotion batch stage failed pipeline_id=%s batch=%s",
            pipeline_id,
            batch_index,
        )


def record_activity_for_pipeline(
    *,
    pipeline_id: str,
    activity_index: int,
    activity_id: str,
    target_pdd_ids: list[str] | None,
    success: bool,
    skipped: bool = False,
    error: str = "",
) -> None:
    if activity_index not in {0, 1}:
        return
    if skipped:
        status = STAGE_SKIPPED
        err = error or "活动跳过"
    elif success:
        status = STAGE_SUCCESS
        err = ""
    else:
        status = STAGE_FAILED
        err = error or "活动报名失败"

    field_status = "activity_1_status" if activity_index == 0 else "activity_2_status"
    field_error = "activity_1_error" if activity_index == 0 else "activity_2_error"
    field_id = "activity_1_id" if activity_index == 0 else "activity_2_id"

    pdd_set = {str(x).strip() for x in (target_pdd_ids or []) if str(x).strip()}

    try:
        with session_scope() as session:
            rows = session.query(IntegratedPipelineBatchProductStageORM).filter_by(pipeline_id=pipeline_id).all()
            for row in rows:
                pid = str(row.pdd_product_id or "").strip()
                if pdd_set and pid and pid not in pdd_set:
                    continue
                setattr(row, field_id, str(activity_id or "").strip())
                setattr(row, field_status, status)
                setattr(row, field_error, err)
                row.updated_at = datetime.now()
    except Exception:
        logger.exception(
            "record activity stage failed pipeline_id=%s activity_index=%s",
            pipeline_id,
            activity_index,
        )


def list_pipeline_batch_product_stages(
    *,
    pipeline_id: str,
    batch_index: int | None = None,
) -> list[dict[str, Any]]:
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id:
        return []
    try:
        with session_scope() as session:
            query = session.query(IntegratedPipelineBatchProductStageORM).filter_by(pipeline_id=pipeline_id)
            if batch_index is not None:
                query = query.filter_by(batch_index=int(batch_index))
            rows = query.order_by(
                IntegratedPipelineBatchProductStageORM.batch_index,
                IntegratedPipelineBatchProductStageORM.product_selector,
            ).all()
            return [
                {
                    "record_id": row.record_id,
                    "pipeline_id": row.pipeline_id,
                    "account_id": row.account_id,
                    "batch_index": row.batch_index,
                    "product_selector": row.product_selector,
                    "listing_label": row.listing_label,
                    "pdd_product_id": row.pdd_product_id,
                    "mapping_id": row.mapping_id,
                    "listing_status": row.listing_status,
                    "listing_error": row.listing_error,
                    "limited_time_status": row.limited_time_status,
                    "limited_time_error": row.limited_time_error,
                    "promotion_status": row.promotion_status,
                    "promotion_error": row.promotion_error,
                    "activity_1_id": row.activity_1_id,
                    "activity_1_status": row.activity_1_status,
                    "activity_1_error": row.activity_1_error,
                    "activity_2_id": row.activity_2_id,
                    "activity_2_status": row.activity_2_status,
                    "activity_2_error": row.activity_2_error,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                    "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                }
                for row in rows
            ]
    except Exception:
        logger.exception("list pipeline batch product stages failed pipeline_id=%s", pipeline_id)
        return []

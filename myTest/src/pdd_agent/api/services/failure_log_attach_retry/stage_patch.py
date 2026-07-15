"""失败日志挂回原链路 — 每批商品状态精准更新（只动匹配行）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
    STAGE_FAILED,
    STAGE_PENDING,
    STAGE_SKIPPED,
    STAGE_SUCCESS,
)
from pdd_agent.core.logging import get_logger
from pdd_agent.db.models import IntegratedPipelineBatchProductStageORM
from pdd_agent.db.session import session_scope

logger = get_logger(__name__)

_ALLOWED_STAGE = frozenset({STAGE_PENDING, STAGE_SUCCESS, STAGE_FAILED, STAGE_SKIPPED, ""})


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _validate_status(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    text = _norm(value)
    if text and text not in _ALLOWED_STAGE:
        raise ValueError(f"invalid_{field}:{text}")
    return text


def patch_batch_product_stage(
    *,
    pipeline_id: str,
    batch_index: int | None = None,
    product_selector: str = "",
    pdd_product_id: str = "",
    mapping_id: str | None = None,
    listing_status: str | None = None,
    listing_error: str | None = None,
    limited_time_status: str | None = None,
    limited_time_error: str | None = None,
    promotion_status: str | None = None,
    promotion_error: str | None = None,
    activity_1_status: str | None = None,
    activity_1_error: str | None = None,
    activity_2_status: str | None = None,
    activity_2_error: str | None = None,
    set_pdd_product_id: str | None = None,
    set_mapping_id: str | None = None,
) -> dict[str, Any]:
    """
    精准更新原链路某一商品行的阶段状态。

    定位优先级：product_selector（+可选 batch_index）> pdd_product_id（+可选 batch_index）。
    不修改其它商品行。
    """
    pid = _norm(pipeline_id)
    if not pid:
        raise ValueError("pipeline_id_required")

    selector = _norm(product_selector)
    pdd_id = _norm(pdd_product_id)
    if not selector and not pdd_id:
        raise ValueError("product_selector_or_pdd_product_id_required")

    listing_status = _validate_status(listing_status, field="listing_status")
    limited_time_status = _validate_status(limited_time_status, field="limited_time_status")
    promotion_status = _validate_status(promotion_status, field="promotion_status")
    activity_1_status = _validate_status(activity_1_status, field="activity_1_status")
    activity_2_status = _validate_status(activity_2_status, field="activity_2_status")

    updated: list[dict[str, Any]] = []
    try:
        with session_scope() as session:
            query = session.query(IntegratedPipelineBatchProductStageORM).filter_by(pipeline_id=pid)
            if batch_index is not None:
                query = query.filter_by(batch_index=int(batch_index))
            rows = query.all()
            matched: list[IntegratedPipelineBatchProductStageORM] = []
            if selector:
                for row in rows:
                    if _norm(row.product_selector) == selector or _norm(row.listing_label) == selector:
                        matched.append(row)
            if not matched and pdd_id:
                for row in rows:
                    if _norm(row.pdd_product_id) == pdd_id:
                        matched.append(row)
            if not matched:
                return {
                    "ok": False,
                    "updated": 0,
                    "reason": "stage_row_not_found",
                    "pipeline_id": pid,
                    "batch_index": batch_index,
                    "product_selector": selector,
                    "pdd_product_id": pdd_id,
                    "items": [],
                }

            now = datetime.now()
            for row in matched:
                if listing_status is not None:
                    row.listing_status = listing_status or STAGE_PENDING
                if listing_error is not None:
                    row.listing_error = _norm(listing_error)
                if limited_time_status is not None:
                    row.limited_time_status = limited_time_status or STAGE_PENDING
                if limited_time_error is not None:
                    row.limited_time_error = _norm(limited_time_error)
                if promotion_status is not None:
                    row.promotion_status = promotion_status or STAGE_PENDING
                if promotion_error is not None:
                    row.promotion_error = _norm(promotion_error)
                if activity_1_status is not None:
                    row.activity_1_status = activity_1_status or STAGE_PENDING
                if activity_1_error is not None:
                    row.activity_1_error = _norm(activity_1_error)
                if activity_2_status is not None:
                    row.activity_2_status = activity_2_status or STAGE_PENDING
                if activity_2_error is not None:
                    row.activity_2_error = _norm(activity_2_error)
                if set_pdd_product_id is not None:
                    text = _norm(set_pdd_product_id)
                    if text:
                        row.pdd_product_id = text
                if set_mapping_id is not None:
                    text = _norm(set_mapping_id)
                    if text:
                        row.mapping_id = text
                elif mapping_id is not None:
                    text = _norm(mapping_id)
                    if text:
                        row.mapping_id = text
                row.updated_at = now
                updated.append(
                    {
                        "record_id": row.record_id,
                        "batch_index": row.batch_index,
                        "product_selector": row.product_selector,
                        "pdd_product_id": row.pdd_product_id,
                        "listing_status": row.listing_status,
                        "limited_time_status": row.limited_time_status,
                        "promotion_status": row.promotion_status,
                        "activity_1_status": row.activity_1_status,
                        "activity_2_status": row.activity_2_status,
                    }
                )
    except ValueError:
        raise
    except Exception:
        logger.exception(
            "patch batch product stage failed pipeline_id=%s selector=%s pdd=%s",
            pid,
            selector,
            pdd_id,
        )
        raise

    return {
        "ok": True,
        "updated": len(updated),
        "reason": "",
        "pipeline_id": pid,
        "batch_index": batch_index,
        "product_selector": selector,
        "pdd_product_id": pdd_id,
        "items": updated,
    }

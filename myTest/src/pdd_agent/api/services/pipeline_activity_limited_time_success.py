"""
整合链路 — 活动仅使用「限时限量购提交成功」的商品 ID。

与 pipeline_service 主流程解耦：由 meta.activity_limited_time_success_only 开关控制，
开启时在 _on_limited_time_finished 等节点走本模块，未开启时行为与原来一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, get_queue_task_by_run_id, update_integrated_pipeline
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)

META_FLAG_KEY = "activity_limited_time_success_only"
META_ACTIVITY_PDD_IDS_KEY = "activity_pdd_product_ids"
META_LT_SUCCESS_PDD_IDS_KEY = "limited_time_success_pdd_product_ids"
META_LT_SUCCESS_MAPPING_IDS_KEY = "limited_time_success_mapping_ids"


@dataclass(frozen=True)
class LimitedTimeSuccessProducts:
    """限时限量购成功后可用于活动/推广的商品 ID。"""

    pdd_product_ids: list[str]
    mapping_ids: list[str]
    source: str = ""
    detail: str = ""


def is_activity_limited_time_success_only(meta: dict[str, Any] | None) -> bool:
    return bool((meta or {}).get(META_FLAG_KEY))


def is_activity_limited_time_success_only_row(row) -> bool:
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    return is_activity_limited_time_success_only(meta)


def _iter_limited_time_result_items(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    items: list[dict[str, Any]] = []
    bucket = result.get("results")
    if isinstance(bucket, list):
        items.extend(item for item in bucket if isinstance(item, dict))
    if result.get("status") is not None or result.get("step"):
        items.append(result)
    return items


def _kept_ids_from_price_filter(price_filter: dict[str, Any] | None) -> list[str]:
    if not isinstance(price_filter, dict):
        return []
    kept = price_filter.get("kept_product_ids")
    if not isinstance(kept, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in kept if str(item).strip()))


def extract_limited_time_success_products(
    result: dict[str, Any] | None,
    *,
    account_id: str,
    fallback_pdd_ids: list[str] | None = None,
    fallback_mapping_ids: list[str] | None = None,
) -> LimitedTimeSuccessProducts:
    """
    从限时限量购 run 结果解析「已提交创建成功」的商品 ID。

    判定：result item status=success 且 step=activity_created；
    商品集合优先取 price_filter.kept_product_ids，否则取 selected_pdd_product_ids。
    """
    fallback_pdd_ids = list(dict.fromkeys(str(x).strip() for x in (fallback_pdd_ids or []) if str(x).strip()))
    fallback_mapping_ids = list(
        dict.fromkeys(str(x).strip() for x in (fallback_mapping_ids or []) if str(x).strip())
    )
    success_pdd_ids: list[str] = []

    for item in _iter_limited_time_result_items(result):
        if str(item.get("status") or "").strip().lower() != "success":
            continue
        if str(item.get("step") or "").strip() != "activity_created":
            continue
        kept = _kept_ids_from_price_filter(item.get("price_filter"))
        if kept:
            success_pdd_ids.extend(kept)
        else:
            selected = item.get("selected_pdd_product_ids")
            if isinstance(selected, list):
                success_pdd_ids.extend(str(x).strip() for x in selected if str(x).strip())

    success_pdd_ids = list(dict.fromkeys(success_pdd_ids))
    if not success_pdd_ids:
        return LimitedTimeSuccessProducts(
            pdd_product_ids=[],
            mapping_ids=[],
            source="none",
            detail="限时限量购未产生成功商品（整单失败或未提交创建）",
        )

    mapping_ids = resolve_mapping_ids_for_pdd_products(
        account_id,
        success_pdd_ids,
        fallback_mapping_ids=fallback_mapping_ids,
    )
    detail = f"限时限量购成功 {len(success_pdd_ids)} 个商品"
    if len(success_pdd_ids) < len(fallback_pdd_ids):
        detail += f"（上架 {len(fallback_pdd_ids)} 个，已过滤 {len(fallback_pdd_ids) - len(success_pdd_ids)} 个）"
    return LimitedTimeSuccessProducts(
        pdd_product_ids=success_pdd_ids,
        mapping_ids=mapping_ids,
        source="limited_time_success",
        detail=detail,
    )


def resolve_mapping_ids_for_pdd_products(
    account_id: str,
    pdd_product_ids: list[str],
    *,
    fallback_mapping_ids: list[str] | None = None,
) -> list[str]:
    """按 pdd_product_id 顺序解析 published_products.mapping_id。"""
    pdd_product_ids = [str(x).strip() for x in pdd_product_ids if str(x).strip()]
    if not pdd_product_ids:
        return []

    from pdd_agent.db.repositories import get_published_products_by_pdd_product_ids

    rows = get_published_products_by_pdd_product_ids(
        account_id=account_id,
        pdd_product_ids=pdd_product_ids,
    )
    by_pdd = {str(row.pdd_product_id or "").strip(): str(row.mapping_id or "").strip() for row in rows}
    ordered: list[str] = []
    seen: set[str] = set()
    for pid in pdd_product_ids:
        mapping_id = by_pdd.get(pid, "")
        if mapping_id and mapping_id not in seen:
            seen.add(mapping_id)
            ordered.append(mapping_id)

    if ordered:
        return ordered

    fallback = list(dict.fromkeys(str(x).strip() for x in (fallback_mapping_ids or []) if str(x).strip()))
    return fallback


def load_limited_time_run_result(run_id: str) -> dict[str, Any]:
    run_id = str(run_id or "").strip()
    if not run_id:
        return {}
    record = TaskRunStore().load(run_id)
    if not record:
        return {}
    result = record.result
    return result if isinstance(result, dict) else {}


def resolve_activity_product_ids_for_row(row) -> tuple[list[str], list[str]]:
    """活动/推广应使用的商品 ID：开关开启时读 meta 过滤结果，否则读 pipeline 全量。"""
    from pdd_agent.api.services.pipeline_lt_failure_promotion_policy import (
        resolve_traffic_product_ids_if_lt_skip,
    )

    lt_skip = resolve_traffic_product_ids_if_lt_skip(row)
    if lt_skip:
        return lt_skip

    meta = row.meta if isinstance(row.meta, dict) else {}
    if is_activity_limited_time_success_only(meta):
        pdd_ids = list(meta.get(META_ACTIVITY_PDD_IDS_KEY) or meta.get(META_LT_SUCCESS_PDD_IDS_KEY) or [])
        mapping_ids = list(meta.get(META_LT_SUCCESS_MAPPING_IDS_KEY) or [])
        if pdd_ids:
            return pdd_ids, mapping_ids
    return list(row.pdd_product_ids or []), list(row.mapping_ids or [])


def build_limited_time_success_meta_patch(
    extract: LimitedTimeSuccessProducts,
) -> dict[str, Any]:
    return {
        META_ACTIVITY_PDD_IDS_KEY: list(extract.pdd_product_ids),
        META_LT_SUCCESS_PDD_IDS_KEY: list(extract.pdd_product_ids),
        META_LT_SUCCESS_MAPPING_IDS_KEY: list(extract.mapping_ids),
        "limited_time_success_detail": extract.detail,
    }


def handle_pipeline_limited_time_finished_for_activity(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
    schedule_activity_fn,
    advance_store_sequential_fn,
) -> bool:
    """
    限时限量购结束后（仅 activity_limited_time_success_only 开启时调用）。

    schedule_activity_fn(row, meta_patch=..., pdd_ids=..., mapping_ids=...)
    advance_store_sequential_fn(row) — 串行模式下交接下一家。

    返回 True 表示本模块已处理，调用方应 return。
    """
    if not is_activity_limited_time_success_only_row(row):
        return False

    result = result if isinstance(result, dict) else load_limited_time_run_result(run_id)
    extract = extract_limited_time_success_products(
        result,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=list(row.pdd_product_ids or []),
        fallback_mapping_ids=list(row.mapping_ids or []),
    )

    meta_patch: dict[str, Any] = {
        "limited_time_finish_handled": True,
        "limited_time_summary": _summarize_run_message(run_id),
    }
    meta_patch.update(build_limited_time_success_meta_patch(extract))

    if extract.pdd_product_ids:
        if success:
            meta_patch["limited_time_outcome"] = "success"
        else:
            meta_patch["limited_time_outcome"] = "partial_success"
            meta_patch["limited_time_skip_reason"] = error or "限时限量购部分失败，仅成功商品继续活动"
        update_integrated_pipeline(
            row.pipeline_id,
            status="running",
            current_step="limited_time_success_continue",
            pdd_product_ids=extract.pdd_product_ids,
            mapping_ids=extract.mapping_ids,
            error="",
            meta_patch=meta_patch,
        )
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        schedule_activity_fn(
            refreshed,
            meta_patch=meta_patch,
            pdd_ids=extract.pdd_product_ids,
            mapping_ids=extract.mapping_ids,
        )
        logger.info(
            "pipeline %s limited time success-only: schedule activity for pdd_ids=%s (%s)",
            row.pipeline_id,
            extract.pdd_product_ids,
            extract.detail,
        )
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        advance_store_sequential_fn(refreshed)
        return True

    failure_message = error or "限时限量购失败，且无成功商品可报活动"
    from pdd_agent.api.services.pipeline_lt_failure_promotion_policy import (
        maybe_lt_failure_skip_activity_and_enqueue_promotion,
    )

    if maybe_lt_failure_skip_activity_and_enqueue_promotion(
        row,
        run_id=run_id,
        success=False,
        result=result,
        error=failure_message,
        enqueue_traffic_fn=_pipeline_enqueue_traffic_for_lt_failure_promotion,
        advance_store_sequential_fn=advance_store_sequential_fn,
        summarize_run_message_fn=_summarize_limited_time_run_message,
    ):
        return True

    meta_patch["limited_time_outcome"] = "failed"
    update_integrated_pipeline(
        row.pipeline_id,
        status="failed",
        current_step="limited_time_failed",
        error=failure_message,
        meta_patch=meta_patch,
    )
    logger.info(
        "pipeline %s limited time success-only: no eligible products (%s)",
        row.pipeline_id,
        failure_message,
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    advance_store_sequential_fn(refreshed)
    return True


def _summarize_limited_time_run_message(run_id: str) -> str:
    record = TaskRunStore().load(run_id)
    return str(record.message or "") if record else ""


def _pipeline_enqueue_traffic_for_lt_failure_promotion(row, *, meta_patch: dict | None = None) -> None:
    from pdd_agent.api.services.pipeline_service import _enqueue_pipeline_traffic

    _enqueue_pipeline_traffic(row, meta_patch=meta_patch)


def filter_products_for_per_batch_campaign_after_limited_time(
    row,
    *,
    run_id: str,
    success: bool,
    error: str,
    pdd_ids: list[str],
    mapping_ids: list[str],
) -> tuple[list[str], list[str], bool, str]:
    """
    每批限时完成后解析活动用商品 ID。

    返回 (pdd_ids, mapping_ids, should_continue, block_reason)。
    should_continue=False 表示应终止本批活动链。
    """
    if not is_activity_limited_time_success_only_row(row):
        if not success and not bool((row.meta or {}).get("continue_after_limited_time_failure")):
            return pdd_ids, mapping_ids, False, error or "限时限量购设置失败"
        return pdd_ids, mapping_ids, True, ""

    result = load_limited_time_run_result(run_id)
    extract = extract_limited_time_success_products(
        result,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=pdd_ids,
        fallback_mapping_ids=mapping_ids,
    )
    if extract.pdd_product_ids:
        return extract.pdd_product_ids, extract.mapping_ids, True, extract.detail

    return [], [], False, error or "限时限量购无成功商品，跳过本批活动"


def reconcile_pipeline_waiting_activity(row):
    """
    修正 waiting_activity 与队列/run 状态不一致（例如 campaign 任务已 failed 但 pipeline 仍显示等待）。
    """
    if not row:
        return row
    if str(getattr(row, "current_step", "") or "") != "waiting_activity":
        return row

    campaign_run_id = str(getattr(row, "campaign_run_id", "") or "").strip()
    if not campaign_run_id:
        return row

    scheduled_at = getattr(row, "scheduled_activity_at", None)
    task = get_queue_task_by_run_id(campaign_run_id)
    if task:
        task_status = str(task.status or "")
        if task_status == "queued":
            if scheduled_at and scheduled_at <= datetime.now():
                logger.debug(
                    "pipeline %s waiting_activity: campaign queued overdue, worker will claim",
                    row.pipeline_id,
                )
            return row
        if task_status in {"failed", "canceled"}:
            err = str(task.error or "").strip() or f"活动任务已{task_status}"
            update_integrated_pipeline(
                row.pipeline_id,
                status="failed" if task_status == "failed" else "canceled",
                current_step="activity_failed" if task_status == "failed" else "canceled",
                error=err,
                meta_patch={"campaign_task_reconciled": True},
            )
            logger.warning(
                "reconciled pipeline %s waiting_activity -> %s (run_id=%s)",
                row.pipeline_id,
                task_status,
                campaign_run_id,
            )
            return get_integrated_pipeline(row.pipeline_id) or row

    record = TaskRunStore().load(campaign_run_id)
    if record:
        status = str(record.status.value if hasattr(record.status, "value") else record.status)
        if status in {"failed", "canceled"}:
            err = str(record.message or "").strip() or f"活动子任务{status}"
            update_integrated_pipeline(
                row.pipeline_id,
                status=status,
                current_step="activity_failed" if status == "failed" else "canceled",
                error=err,
                meta_patch={"campaign_run_reconciled": True},
            )
            logger.warning(
                "reconciled pipeline %s waiting_activity from run_record status=%s",
                row.pipeline_id,
                status,
            )
            return get_integrated_pipeline(row.pipeline_id) or row

    return row


def _summarize_run_message(run_id: str) -> str:
    record = TaskRunStore().load(run_id)
    return str(record.message or "") if record else ""

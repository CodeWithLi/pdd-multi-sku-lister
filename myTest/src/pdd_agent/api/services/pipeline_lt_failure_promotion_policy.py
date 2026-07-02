"""
可选策略：限时限量购失败 → 跳过活动报名 → 仍创建推广。

与 pipeline_service 主流程解耦：由链路 meta.promote_after_limited_time_failure 开关控制；
推广商品 ID 来源由系统配置 pipeline.lt_failure_skip_activity_promotion_product_source 决定。

回滚方式：
  1. 删除 pipeline_service / pipeline_activity_limited_time_success 等处的引用；或
  2. 链路 meta 设置 promote_after_limited_time_failure=false。
"""

from __future__ import annotations

from typing import Any, Callable

from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, update_integrated_pipeline

logger = get_logger(__name__)

META_FLAG = "promote_after_limited_time_failure"
CAMPAIGN_OUTCOME = "limited_time_failed_skip_activity"
PRODUCT_SOURCE_LISTING = "listing_success"
PRODUCT_SOURCE_LT = "limited_time_success"
META_PROMOTION_PDD_IDS_KEY = "lt_failure_skip_activity_promotion_pdd_product_ids"
META_PROMOTION_MAPPING_IDS_KEY = "lt_failure_skip_activity_promotion_mapping_ids"
META_TRAFFIC_SKIP_REASON_KEY = "traffic_skip_reason"


def is_promote_after_limited_time_failure_enabled(row) -> bool:
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    return bool(meta.get(META_FLAG))


def get_lt_failure_promotion_product_source() -> str:
    settings = load_yaml_settings()
    source = str(settings.pipeline.lt_failure_skip_activity_promotion_product_source or "").strip()
    if source not in {PRODUCT_SOURCE_LISTING, PRODUCT_SOURCE_LT}:
        return PRODUCT_SOURCE_LISTING
    return source


def is_final_limited_time_decision_row(row) -> bool:
    """分批模式下须等全部批次限时跑完；非分批则当前即最终决策点。"""
    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        is_per_batch_limited_time_enabled,
    )

    if not is_per_batch_limited_time_enabled(row):
        return True

    from pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy import (
        _is_final_per_batch_limited_time_batch,
    )

    return _is_final_per_batch_limited_time_batch(row)


def _activity_would_still_run(row, *, success: bool) -> bool:
    """限时成功后仍走原活动路径；限时失败且开启「限时失败仍继续」时也仍报活动。"""
    if success:
        return True
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    return bool(meta.get("continue_after_limited_time_failure"))


def resolve_listing_success_product_ids(row) -> tuple[list[str], list[str], str]:
    from pdd_agent.api.services.pipeline_per_batch_limited_time import (
        is_per_batch_limited_time_enabled,
        prepare_pipeline_row_for_post_listing_steps,
        resolve_activity_products_after_per_batch_listing,
    )

    refreshed = row
    if is_per_batch_limited_time_enabled(row):
        refreshed = prepare_pipeline_row_for_post_listing_steps(row) or row
    pdd_ids = list(refreshed.pdd_product_ids or [])
    mapping_ids = list(refreshed.mapping_ids or [])
    if is_per_batch_limited_time_enabled(refreshed):
        pdd_ids, mapping_ids = resolve_activity_products_after_per_batch_listing(
            refreshed,
            pdd_ids,
            mapping_ids,
        )
    detail = f"上架成功商品 {len(pdd_ids)} 个"
    return list(dict.fromkeys(pdd_ids)), list(dict.fromkeys(mapping_ids)), detail


def resolve_limited_time_success_product_ids(
    row,
    *,
    run_id: str,
    result: dict[str, Any] | None,
) -> tuple[list[str], list[str], str]:
    from pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy import (
        _build_merged_activity_products,
        _policy_applies,
    )
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        extract_limited_time_success_products,
        load_limited_time_run_result,
        resolve_mapping_ids_for_pdd_products,
    )

    if _policy_applies(row):
        merged = _build_merged_activity_products(row, run_id=run_id, result=result)
        if merged.pdd_product_ids:
            return list(merged.pdd_product_ids), list(merged.mapping_ids), merged.detail

    payload = result if isinstance(result, dict) else load_limited_time_run_result(run_id)
    extract = extract_limited_time_success_products(
        payload,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=list(row.pdd_product_ids or []),
        fallback_mapping_ids=list(row.mapping_ids or []),
    )
    if extract.pdd_product_ids:
        return list(extract.pdd_product_ids), list(extract.mapping_ids), extract.detail

    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    accumulated = list(meta.get("accumulated_limited_time_success_pdd_product_ids") or [])
    if accumulated:
        mapping_ids = resolve_mapping_ids_for_pdd_products(
            str(row.account_id or ""),
            accumulated,
            fallback_mapping_ids=list(
                meta.get("accumulated_limited_time_success_mapping_ids") or []
            ),
        )
        detail = f"跨批累计限时成功 {len(accumulated)} 个商品"
        return accumulated, mapping_ids, detail

    return [], [], "无限时提交成功商品"


def resolve_lt_failure_skip_activity_promotion_products(
    row,
    *,
    run_id: str,
    result: dict[str, Any] | None,
) -> tuple[list[str], list[str], str]:
    source = get_lt_failure_promotion_product_source()
    if source == PRODUCT_SOURCE_LT:
        return resolve_limited_time_success_product_ids(row, run_id=run_id, result=result)
    return resolve_listing_success_product_ids(row)


def resolve_traffic_product_ids_if_lt_skip(row) -> tuple[list[str], list[str]] | None:
    """推广入队时读取限时失败跳过活动专用商品 ID。"""
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    if str(meta.get("campaign_outcome") or "") != CAMPAIGN_OUTCOME:
        return None
    pdd_ids = list(meta.get(META_PROMOTION_PDD_IDS_KEY) or [])
    mapping_ids = list(meta.get(META_PROMOTION_MAPPING_IDS_KEY) or [])
    if not pdd_ids:
        return None
    return pdd_ids, mapping_ids


def build_lt_failure_skip_activity_meta_patch(
    *,
    error: str,
    pdd_ids: list[str],
    mapping_ids: list[str],
    product_detail: str,
    summarize: str = "",
) -> dict[str, Any]:
    failure_message = str(error or "").strip() or "限时限量购设置失败"
    skip_reason = failure_message
    if product_detail:
        skip_reason = f"{failure_message}；{product_detail}"
    patch: dict[str, Any] = {
        "limited_time_finish_handled": True,
        "limited_time_outcome": "failed",
        "limited_time_skip_reason": failure_message,
        "campaign_outcome": CAMPAIGN_OUTCOME,
        "campaign_skip_reason": skip_reason,
        META_PROMOTION_PDD_IDS_KEY: list(pdd_ids),
        META_PROMOTION_MAPPING_IDS_KEY: list(mapping_ids),
        "lt_failure_skip_activity_promotion_product_source": get_lt_failure_promotion_product_source(),
    }
    if summarize:
        patch["limited_time_summary"] = summarize
    return patch


def _complete_without_traffic(
    row,
    *,
    meta_patch: dict[str, Any],
    traffic_skip_reason: str,
    advance_store_sequential_fn: Callable[[Any], None] | None,
) -> None:
    meta_patch = dict(meta_patch)
    meta_patch[META_TRAFFIC_SKIP_REASON_KEY] = traffic_skip_reason
    update_integrated_pipeline(
        row.pipeline_id,
        status="completed",
        current_step="completed",
        error="",
        meta_patch=meta_patch,
    )
    logger.info(
        "pipeline %s limited time failed, activity skipped, no promotion products: %s",
        row.pipeline_id,
        traffic_skip_reason,
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    if advance_store_sequential_fn:
        advance_store_sequential_fn(refreshed)


def maybe_lt_failure_skip_activity_and_enqueue_promotion(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
    enqueue_traffic_fn: Callable[..., None],
    advance_store_sequential_fn: Callable[[Any], None] | None = None,
    summarize_run_message_fn: Callable[[str], str] | None = None,
) -> bool:
    """
    限时失败且活动不会跑时：跳过活动，立即推广（或无上架成功商品时不推广并完成链路）。

    返回 True 表示本模块已接管，调用方应 return。
    """
    if not row or not is_promote_after_limited_time_failure_enabled(row):
        return False
    if not bool(getattr(row, "auto_promotion", False)):
        return False
    if success:
        return False
    if _activity_would_still_run(row, success=success):
        return False
    if not is_final_limited_time_decision_row(row):
        return False

    summarize = summarize_run_message_fn(run_id) if summarize_run_message_fn else ""
    pdd_ids, mapping_ids, product_detail = resolve_lt_failure_skip_activity_promotion_products(
        row,
        run_id=run_id,
        result=result,
    )
    meta_patch = build_lt_failure_skip_activity_meta_patch(
        error=error,
        pdd_ids=pdd_ids,
        mapping_ids=mapping_ids,
        product_detail=product_detail,
        summarize=summarize,
    )

    source = get_lt_failure_promotion_product_source()
    if not pdd_ids:
        if source == PRODUCT_SOURCE_LISTING:
            _complete_without_traffic(
                row,
                meta_patch=meta_patch,
                traffic_skip_reason="限时失败跳过活动；无上架成功商品，未创建推广",
                advance_store_sequential_fn=advance_store_sequential_fn,
            )
            return True
        return False

    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="limited_time_failed_skip_activity_promotion",
        pdd_product_ids=pdd_ids,
        mapping_ids=mapping_ids,
        error="",
        meta_patch=meta_patch,
    )
    refreshed = get_integrated_pipeline(row.pipeline_id) or row
    enqueue_traffic_fn(refreshed, meta_patch=meta_patch)
    logger.info(
        "pipeline %s limited time failed, skip activity, enqueue promotion pdd_ids=%s source=%s",
        row.pipeline_id,
        pdd_ids,
        source,
    )
    if advance_store_sequential_fn:
        advance_store_sequential_fn(refreshed)
    return True


def enrich_pipeline_step_infos(
    steps: list[dict[str, Any]],
    row,
    *,
    meta: dict[str, Any],
    limited_time_outcome: str,
    campaign_outcome: str,
    campaign_skip_reason: str,
    auto_promotion: bool,
) -> None:
    """补充链路步骤面板文案（由 pipeline_service._step_infos 调用）。"""
    if not is_promote_after_limited_time_failure_enabled(row):
        return
    if campaign_outcome != CAMPAIGN_OUTCOME:
        return

    for step in steps:
        key = str(step.get("key") or "")
        if key == "activity":
            step["status"] = "skipped"
            step["detail"] = campaign_skip_reason or "限时限量购失败，已跳过活动报名"
        elif key == "traffic" and auto_promotion:
            if str(meta.get(META_TRAFFIC_SKIP_REASON_KEY) or "").strip():
                step["status"] = "skipped"
                step["detail"] = str(meta[META_TRAFFIC_SKIP_REASON_KEY])
            elif limited_time_outcome == "failed":
                step["detail"] = "限时失败跳过活动，立即创建推广"

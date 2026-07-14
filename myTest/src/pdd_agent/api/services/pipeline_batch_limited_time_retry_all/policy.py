"""分批限时限量购 — 一键全部重跑（手动）。"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline

logger = get_logger(__name__)


def _meta(row) -> dict[str, Any]:
    raw = getattr(row, "meta", None) if row is not None else None
    return dict(raw) if isinstance(raw, dict) else {}


def list_candidate_batch_indices(row) -> list[int]:
    meta = _meta(row)
    throttle = dict(meta.get("listing_throttle") or {})
    total = int(throttle.get("total_batches") or 0)
    if total > 0:
        return list(range(total))

    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
        list_pipeline_batch_product_stages,
    )

    items = list_pipeline_batch_product_stages(pipeline_id=str(getattr(row, "pipeline_id", "") or ""))
    return sorted(
        {
            int(item.get("batch_index") or 0)
            for item in items
            if item.get("batch_index") is not None
        }
    )


def list_all_retryable_batches(row) -> list[dict[str, Any]]:
    """
    手动「全部重跑」候选：与单批按钮同一套 eligibility，不受自动重跑次数限制。
    """
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        evaluate_batch_limited_time_retry_eligibility,
        is_standard_per_batch_lt_aggregate_pipeline,
    )

    if row is None:
        return []
    if not is_standard_per_batch_lt_aggregate_pipeline(row):
        return []

    result: list[dict[str, Any]] = []
    for batch_index in list_candidate_batch_indices(row):
        eligibility = evaluate_batch_limited_time_retry_eligibility(row, int(batch_index))
        if not eligibility.get("eligible"):
            continue
        result.append(
            {
                "batch_index": int(batch_index),
                "retry_count": int(eligibility.get("retry_count") or 0),
                "pdd_product_ids": list(eligibility.get("pdd_product_ids") or []),
            }
        )
    return result


def start_all_batch_limited_time_retries(pipeline_id: str) -> dict[str, Any]:
    """
    对当前链路所有可重跑批次依次 start：
      - 第一批立即入队执行；
      - 后续批次进入现有 pending 串行队列。
    完全复用 start_batch_limited_time_retry。
    """
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        build_batch_limited_time_retry_public_state,
        start_batch_limited_time_retry,
    )

    pipeline_id = str(pipeline_id or "").strip()
    row = get_integrated_pipeline(pipeline_id)
    if not row:
        raise ValueError("pipeline_not_found")

    candidates = list_all_retryable_batches(row)
    if not candidates:
        raise ValueError("no_limited_time_retry_targets")

    started: list[dict[str, Any]] = []
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    active_run_id = ""

    for item in candidates:
        batch_index = int(item["batch_index"])
        refreshed = get_integrated_pipeline(pipeline_id) or row
        from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
            evaluate_batch_limited_time_retry_eligibility,
        )

        eligibility = evaluate_batch_limited_time_retry_eligibility(refreshed, batch_index)
        if not eligibility.get("eligible"):
            skipped.append(
                {
                    "batch_index": batch_index,
                    "reason": str(eligibility.get("reason") or "not_eligible"),
                }
            )
            continue
        try:
            result = start_batch_limited_time_retry(pipeline_id, batch_index=batch_index)
        except ValueError as exc:
            skipped.append({"batch_index": batch_index, "reason": str(exc)})
            logger.info(
                "pipeline %s start-all batch lt retry skip batch=%s reason=%s",
                pipeline_id,
                batch_index + 1,
                exc,
            )
            continue

        entry = {
            "batch_index": batch_index,
            "retry_count": int(result.get("retry_count") or item.get("retry_count") or 0),
            "pdd_product_ids": list(result.get("pdd_product_ids") or item.get("pdd_product_ids") or []),
            "limited_time_run_id": str(result.get("limited_time_run_id") or ""),
            "queued": bool(result.get("queued")),
        }
        if entry["queued"]:
            queued.append(entry)
        else:
            started.append(entry)
            if entry["limited_time_run_id"]:
                active_run_id = entry["limited_time_run_id"]

        logger.info(
            "pipeline %s start-all batch lt retry batch=%s queued=%s retry_count=%s",
            pipeline_id,
            batch_index + 1,
            entry["queued"],
            entry["retry_count"],
        )

    if not started and not queued:
        raise ValueError("no_limited_time_retry_targets")

    refreshed = get_integrated_pipeline(pipeline_id) or row
    total_retry_count = sum(int(x.get("retry_count") or 0) for x in [*started, *queued])
    return {
        "pipeline_id": pipeline_id,
        "started_batches": started,
        "queued_batches": queued,
        "skipped_batches": skipped,
        "batch_count": len(started) + len(queued),
        "retry_count": total_retry_count,
        "limited_time_run_id": active_run_id
        or str((build_batch_limited_time_retry_public_state(refreshed).get("limited_time_run_id") or "")),
        "batch_limited_time_retry": build_batch_limited_time_retry_public_state(refreshed),
    }

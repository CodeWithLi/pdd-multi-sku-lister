"""
分批限时限量购 — 自动重跑策略。

在标准「每批限时」模式下，当全部分批上架完成且某批存在
「上架成功 + 限时失败」商品时，自动调用现有
`start_batch_limited_time_retry`（含按趟拆分 / 活动改期），无需手点。

配置：
  - enabled：开关
  - max_attempts：每个上架批次最多自动重跑轮次（默认 1）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.constants import (
    DEFAULT_MAX_ATTEMPTS,
    MAX_ATTEMPTS_CAP,
    META_ENABLED_KEY,
    META_MAX_ATTEMPTS_KEY,
    META_STATE_KEY,
    MIN_ATTEMPTS,
)
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, update_integrated_pipeline

logger = get_logger(__name__)


def _meta(row) -> dict[str, Any]:
    raw = getattr(row, "meta", None) if row is not None else None
    return dict(raw) if isinstance(raw, dict) else {}


def _clamp_max_attempts(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = DEFAULT_MAX_ATTEMPTS
    return max(MIN_ATTEMPTS, min(MAX_ATTEMPTS_CAP, n))


def auto_retry_meta_patch(*, enabled: bool, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> dict[str, Any]:
    """启动链路时写入 meta（仅标准每批限时场景调用方应传入）。"""
    if not enabled:
        return {}
    attempts = _clamp_max_attempts(max_attempts)
    return {
        META_ENABLED_KEY: True,
        META_MAX_ATTEMPTS_KEY: attempts,
        META_STATE_KEY: {
            "enabled": True,
            "max_attempts": attempts,
            "batch_attempts": {},
            "started_batch_indices": [],
            "last_scan_at": "",
            "last_reason": "",
            "last_started_batches": [],
        },
    }


def auto_retry_state(row) -> dict[str, Any]:
    state = _meta(row).get(META_STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}


def is_auto_retry_enabled(row) -> bool:
    if row is None:
        return False
    meta = _meta(row)
    if META_ENABLED_KEY in meta:
        return bool(meta.get(META_ENABLED_KEY))
    state = auto_retry_state(row)
    if "enabled" in state:
        return bool(state.get("enabled"))
    return False


def resolve_max_attempts(row) -> int:
    meta = _meta(row)
    if META_MAX_ATTEMPTS_KEY in meta:
        return _clamp_max_attempts(meta.get(META_MAX_ATTEMPTS_KEY))
    state = auto_retry_state(row)
    if "max_attempts" in state:
        return _clamp_max_attempts(state.get("max_attempts"))
    return DEFAULT_MAX_ATTEMPTS


def get_batch_attempts(row, batch_index: int) -> int:
    state = auto_retry_state(row)
    attempts_map = state.get("batch_attempts") or {}
    if not isinstance(attempts_map, dict):
        return 0
    key = str(int(batch_index))
    try:
        return max(0, int(attempts_map.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _save_auto_retry_state(row, patch: dict[str, Any]) -> None:
    current = auto_retry_state(row)
    current.update(patch)
    current["enabled"] = is_auto_retry_enabled(row)
    current["max_attempts"] = resolve_max_attempts(row)
    update_integrated_pipeline(row.pipeline_id, meta_patch={META_STATE_KEY: current})
    # 同步内存行，避免同一次扫描内后续 patch 读到旧 attempts
    meta = _meta(row)
    meta[META_STATE_KEY] = current
    try:
        row.meta = meta
    except Exception:
        pass


def _increment_batch_attempt(row, batch_index: int) -> int:
    state = auto_retry_state(row)
    attempts_map = dict(state.get("batch_attempts") or {})
    key = str(int(batch_index))
    next_value = get_batch_attempts(row, batch_index) + 1
    attempts_map[key] = next_value
    started = list(state.get("started_batch_indices") or [])
    if int(batch_index) not in started:
        started.append(int(batch_index))
    _save_auto_retry_state(
        row,
        {
            "batch_attempts": attempts_map,
            "started_batch_indices": started,
        },
    )
    return next_value


def build_auto_retry_public_state(row) -> dict[str, Any]:
    state = auto_retry_state(row)
    attempts_map = state.get("batch_attempts") or {}
    if not isinstance(attempts_map, dict):
        attempts_map = {}
    normalized_attempts: dict[str, int] = {}
    for key, value in attempts_map.items():
        try:
            normalized_attempts[str(key)] = max(0, int(value or 0))
        except (TypeError, ValueError):
            continue
    return {
        "enabled": is_auto_retry_enabled(row),
        "max_attempts": resolve_max_attempts(row),
        "batch_attempts": normalized_attempts,
        "started_batch_indices": [int(x) for x in (state.get("started_batch_indices") or [])],
        "last_scan_at": str(state.get("last_scan_at") or ""),
        "last_reason": str(state.get("last_reason") or ""),
        "last_started_batches": [int(x) for x in (state.get("last_started_batches") or [])],
    }


def list_candidate_batch_indices(row) -> list[int]:
    meta = _meta(row)
    throttle = dict(meta.get("listing_throttle") or {})
    total = int(throttle.get("total_batches") or 0)
    if total > 0:
        return list(range(total))

    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
        list_pipeline_batch_product_stages,
    )

    items = list_pipeline_batch_product_stages(pipeline_id=str(row.pipeline_id or ""))
    indices = sorted(
        {
            int(item.get("batch_index") or 0)
            for item in items
            if item.get("batch_index") is not None
        }
    )
    return indices


def list_auto_retryable_batches(row) -> list[dict[str, Any]]:
    """返回可自动重跑的批次摘要（已扣减次数上限）。"""
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        evaluate_batch_limited_time_retry_eligibility,
        is_standard_per_batch_lt_aggregate_pipeline,
    )

    if row is None or not is_auto_retry_enabled(row):
        return []
    if not is_standard_per_batch_lt_aggregate_pipeline(row):
        return []

    max_attempts = resolve_max_attempts(row)
    result: list[dict[str, Any]] = []
    for batch_index in list_candidate_batch_indices(row):
        attempts = get_batch_attempts(row, batch_index)
        if attempts >= max_attempts:
            continue
        eligibility = evaluate_batch_limited_time_retry_eligibility(row, int(batch_index))
        if not eligibility.get("eligible"):
            continue
        result.append(
            {
                "batch_index": int(batch_index),
                "attempts": attempts,
                "max_attempts": max_attempts,
                "retry_count": int(eligibility.get("retry_count") or 0),
                "pdd_product_ids": list(eligibility.get("pdd_product_ids") or []),
            }
        )
    return result


def maybe_auto_start_batch_limited_time_retries(row, *, reason: str = "") -> bool:
    """
    扫描并自动启动（或排队）分批限时重跑。

    复用 `start_batch_limited_time_retry`：按趟拆分、活动 defer/改期与手动入口一致。
    返回 True 表示至少启动或排队了一个批次。
    """
    if row is None:
        return False

    pipeline_id = str(getattr(row, "pipeline_id", "") or "").strip()
    if not pipeline_id:
        return False

    refreshed = get_integrated_pipeline(pipeline_id) or row
    if not is_auto_retry_enabled(refreshed):
        return False

    from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
        is_standard_per_batch_lt_aggregate_pipeline,
        start_batch_limited_time_retry,
    )
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_eligibility import (
        is_pipeline_listing_batches_complete,
    )

    if not is_standard_per_batch_lt_aggregate_pipeline(refreshed):
        return False
    if not is_pipeline_listing_batches_complete(refreshed):
        return False

    candidates = list_auto_retryable_batches(refreshed)
    if not candidates:
        _save_auto_retry_state(
            refreshed,
            {
                "last_scan_at": datetime.now().isoformat(),
                "last_reason": reason or "scan_no_candidates",
                "last_started_batches": [],
            },
        )
        return False

    started_batches: list[int] = []
    for item in candidates:
        batch_index = int(item["batch_index"])
        # 重新取最新行：前一次 start 可能已切到 limited_time / pending
        refreshed = get_integrated_pipeline(pipeline_id) or refreshed
        if get_batch_attempts(refreshed, batch_index) >= resolve_max_attempts(refreshed):
            continue
        from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
            evaluate_batch_limited_time_retry_eligibility,
        )

        eligibility = evaluate_batch_limited_time_retry_eligibility(refreshed, batch_index)
        if not eligibility.get("eligible"):
            continue
        try:
            start_batch_limited_time_retry(pipeline_id, batch_index=batch_index)
        except ValueError as exc:
            logger.info(
                "pipeline %s auto batch lt retry skip batch=%s reason=%s",
                pipeline_id,
                batch_index + 1,
                exc,
            )
            continue
        refreshed = get_integrated_pipeline(pipeline_id) or refreshed
        attempt_no = _increment_batch_attempt(refreshed, batch_index)
        started_batches.append(batch_index)
        logger.info(
            "pipeline %s auto batch lt retry started batch=%s attempt=%s/%s reason=%s retry_count=%s",
            pipeline_id,
            batch_index + 1,
            attempt_no,
            resolve_max_attempts(refreshed),
            reason or "auto",
            item.get("retry_count"),
        )

    refreshed = get_integrated_pipeline(pipeline_id) or refreshed
    _save_auto_retry_state(
        refreshed,
        {
            "last_scan_at": datetime.now().isoformat(),
            "last_reason": reason or "auto_scan",
            "last_started_batches": started_batches,
        },
    )
    return bool(started_batches)

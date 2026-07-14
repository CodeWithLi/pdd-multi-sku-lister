"""
分批限时限量购自动重跑 — 与主链路 / 队列的薄桥接。

仅在 pipeline_service、listing continue、创建参数处引用，避免散落修改。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline

logger = get_logger(__name__)


def auto_retry_meta_patch(*, enabled: bool, max_attempts: int = 1) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry import policy

    return policy.auto_retry_meta_patch(enabled=enabled, max_attempts=max_attempts)


def build_auto_retry_public_state(row) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry import policy

    return policy.build_auto_retry_public_state(row)


def maybe_auto_start_batch_limited_time_retries(row, *, reason: str = "") -> bool:
    """安全触发：内部吞异常，避免打断主链路。"""
    from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry import policy

    if row is None:
        return False
    try:
        return bool(
            policy.maybe_auto_start_batch_limited_time_retries(row, reason=reason or "bridge")
        )
    except Exception:
        logger.exception(
            "pipeline %s auto batch lt retry scan failed reason=%s",
            getattr(row, "pipeline_id", ""),
            reason,
        )
        return False


def maybe_auto_start_for_pipeline_id(pipeline_id: str, *, reason: str = "") -> bool:
    pid = str(pipeline_id or "").strip()
    if not pid:
        return False
    row = get_integrated_pipeline(pid)
    if not row:
        return False
    return maybe_auto_start_batch_limited_time_retries(row, reason=reason)

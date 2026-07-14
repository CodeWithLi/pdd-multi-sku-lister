"""分批限时一键全部重跑 — 薄桥接。"""

from __future__ import annotations

from typing import Any

from pdd_agent.api.services.pipeline_batch_limited_time_retry_all import policy


def list_all_retryable_batches(row) -> list[dict[str, Any]]:
    return policy.list_all_retryable_batches(row)


def start_all_batch_limited_time_retries(pipeline_id: str) -> dict[str, Any]:
    return policy.start_all_batch_limited_time_retries(pipeline_id)

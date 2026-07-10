"""整合链路 — 分批模式：限时限量购 → 推广 → 活动。"""

from __future__ import annotations

from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.bridge import (
    is_per_batch_lt_traffic_activity_enabled,
    maybe_handle_campaign_finished,
    maybe_handle_limited_time_finished,
    maybe_handle_traffic_finished,
    maybe_record_listing_batch,
    per_batch_lt_traffic_activity_meta_patch,
    should_absorb_queue_task_failure,
)

__all__ = [
    "is_per_batch_lt_traffic_activity_enabled",
    "maybe_handle_campaign_finished",
    "maybe_handle_limited_time_finished",
    "maybe_handle_traffic_finished",
    "maybe_record_listing_batch",
    "per_batch_lt_traffic_activity_meta_patch",
    "should_absorb_queue_task_failure",
]

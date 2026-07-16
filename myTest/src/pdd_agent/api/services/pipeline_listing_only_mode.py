"""Integrated pipeline listing-only mode helpers."""

from __future__ import annotations

from typing import Any


LISTING_ONLY_SKIP_REASON = "仅上架模式已跳过限时限量购、活动和推广"


def apply_listing_only_mode(
    *,
    listing_only: bool,
    activity_ids: list[str],
    auto_promotion: bool,
    auto_limited_time_setup: bool,
    continue_after_limited_time_failure: bool,
    continue_after_activity_failure: bool,
    promote_after_limited_time_failure: bool,
    activity_limited_time_success_only: bool,
    listing_per_batch_limited_time_enabled: bool,
    listing_per_batch_campaign_enabled: bool,
    listing_per_batch_lt_traffic_activity_enabled: bool,
    listing_per_batch_promote_lt_success_only_enabled: bool,
    activity_traffic_batch_enabled: bool,
    batch_limited_time_auto_retry_enabled: bool,
) -> dict[str, Any]:
    if not listing_only:
        return {
            "activity_ids": activity_ids,
            "auto_promotion": auto_promotion,
            "auto_limited_time_setup": auto_limited_time_setup,
            "continue_after_limited_time_failure": continue_after_limited_time_failure,
            "continue_after_activity_failure": continue_after_activity_failure,
            "promote_after_limited_time_failure": promote_after_limited_time_failure,
            "activity_limited_time_success_only": activity_limited_time_success_only,
            "listing_per_batch_limited_time_enabled": listing_per_batch_limited_time_enabled,
            "listing_per_batch_campaign_enabled": listing_per_batch_campaign_enabled,
            "listing_per_batch_lt_traffic_activity_enabled": listing_per_batch_lt_traffic_activity_enabled,
            "listing_per_batch_promote_lt_success_only_enabled": listing_per_batch_promote_lt_success_only_enabled,
            "activity_traffic_batch_enabled": activity_traffic_batch_enabled,
            "batch_limited_time_auto_retry_enabled": batch_limited_time_auto_retry_enabled,
            "meta_patch": {"listing_only": False},
        }

    return {
        "activity_ids": [],
        "auto_promotion": False,
        "auto_limited_time_setup": False,
        "continue_after_limited_time_failure": False,
        "continue_after_activity_failure": False,
        "promote_after_limited_time_failure": False,
        "activity_limited_time_success_only": False,
        "listing_per_batch_limited_time_enabled": False,
        "listing_per_batch_campaign_enabled": False,
        "listing_per_batch_lt_traffic_activity_enabled": False,
        "listing_per_batch_promote_lt_success_only_enabled": listing_per_batch_promote_lt_success_only_enabled,
        "activity_traffic_batch_enabled": False,
        "batch_limited_time_auto_retry_enabled": False,
        "meta_patch": {
            "listing_only": True,
            "auto_limited_time_setup": False,
            "limited_time_outcome": "skipped",
            "limited_time_skip_reason": LISTING_ONLY_SKIP_REASON,
            "campaign_outcome": "skipped",
            "campaign_skip_reason": LISTING_ONLY_SKIP_REASON,
        },
    }


def is_listing_only_pipeline(row: Any) -> bool:
    return bool((getattr(row, "meta", None) or {}).get("listing_only"))


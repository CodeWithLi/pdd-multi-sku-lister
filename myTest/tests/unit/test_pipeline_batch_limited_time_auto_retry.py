"""pipeline_batch_limited_time_auto_retry 单元测试。"""

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.constants import (
    META_ENABLED_KEY,
    META_MAX_ATTEMPTS_KEY,
    META_STATE_KEY,
)
from pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.policy import (
    auto_retry_meta_patch,
    build_auto_retry_public_state,
    get_batch_attempts,
    is_auto_retry_enabled,
    list_auto_retryable_batches,
    maybe_auto_start_batch_limited_time_retries,
    resolve_max_attempts,
)


def _standard_row(*, meta_extra: dict | None = None, **overrides):
    meta = {
        META_ENABLED_KEY: True,
        META_MAX_ATTEMPTS_KEY: 2,
        META_STATE_KEY: {
            "enabled": True,
            "max_attempts": 2,
            "batch_attempts": {},
            "started_batch_indices": [],
        },
        "listing_per_batch_limited_time_enabled": True,
        "listing_throttle": {
            "enabled": True,
            "completed": True,
            "batch_index": 1,
            "total_batches": 2,
        },
    }
    if meta_extra:
        meta.update(meta_extra)
    if "meta" in overrides:
        meta = overrides.pop("meta")
    return SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="acc_1",
        current_step="waiting_activity",
        status="waiting_activity",
        meta=meta,
        **overrides,
    )


def test_auto_retry_meta_patch_empty_when_disabled():
    assert auto_retry_meta_patch(enabled=False) == {}


def test_auto_retry_meta_patch_clamps_attempts():
    patch_data = auto_retry_meta_patch(enabled=True, max_attempts=99)
    assert patch_data[META_ENABLED_KEY] is True
    assert patch_data[META_MAX_ATTEMPTS_KEY] == 10
    assert patch_data[META_STATE_KEY]["max_attempts"] == 10


def test_is_auto_retry_enabled_and_max_attempts():
    row = _standard_row()
    assert is_auto_retry_enabled(row) is True
    assert resolve_max_attempts(row) == 2
    assert get_batch_attempts(row, 0) == 0


def test_build_auto_retry_public_state():
    row = _standard_row(
        meta={
            META_ENABLED_KEY: True,
            META_MAX_ATTEMPTS_KEY: 3,
            META_STATE_KEY: {
                "enabled": True,
                "max_attempts": 3,
                "batch_attempts": {"0": 1},
                "started_batch_indices": [0],
                "last_reason": "scan",
                "last_started_batches": [0],
            },
            "listing_per_batch_limited_time_enabled": True,
            "listing_throttle": {"enabled": True, "total_batches": 2, "completed": True},
        }
    )
    public = build_auto_retry_public_state(row)
    assert public["enabled"] is True
    assert public["max_attempts"] == 3
    assert public["batch_attempts"] == {"0": 1}
    assert public["started_batch_indices"] == [0]
    assert public["last_started_batches"] == [0]


def test_maybe_auto_start_skipped_when_disabled():
    row = _standard_row(meta={"listing_per_batch_limited_time_enabled": True})
    assert maybe_auto_start_batch_limited_time_retries(row, reason="test") is False


@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.policy.get_integrated_pipeline"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.policy.update_integrated_pipeline"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.start_batch_limited_time_retry"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.evaluate_batch_limited_time_retry_eligibility"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.is_standard_per_batch_lt_aggregate_pipeline",
    return_value=True,
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_eligibility.is_pipeline_listing_batches_complete",
    return_value=True,
)
def test_maybe_auto_start_triggers_eligible_batches(
    _listing_complete,
    _is_standard,
    mock_elig,
    mock_start,
    mock_update,
    mock_get,
):
    row = _standard_row()
    mock_get.return_value = row
    mock_elig.side_effect = [
        {
            "eligible": True,
            "batch_index": 0,
            "retry_count": 2,
            "pdd_product_ids": ["p1", "p2"],
        },
        {
            "eligible": False,
            "reason": "no_limited_time_retry_targets",
            "batch_index": 1,
        },
        # second eligibility check inside loop for batch 0
        {
            "eligible": True,
            "batch_index": 0,
            "retry_count": 2,
            "pdd_product_ids": ["p1", "p2"],
        },
    ]
    mock_start.return_value = {
        "pipeline_id": "pipe_1",
        "batch_index": 0,
        "queued": False,
        "retry_count": 2,
    }

    assert maybe_auto_start_batch_limited_time_retries(row, reason="unit") is True
    mock_start.assert_called_once_with("pipe_1", batch_index=0)
    assert mock_update.called


@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.policy.get_integrated_pipeline"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_auto_retry.policy.update_integrated_pipeline"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.start_batch_limited_time_retry"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.evaluate_batch_limited_time_retry_eligibility"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.is_standard_per_batch_lt_aggregate_pipeline",
    return_value=True,
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_eligibility.is_pipeline_listing_batches_complete",
    return_value=True,
)
def test_maybe_auto_start_respects_max_attempts(
    _listing_complete,
    _is_standard,
    mock_elig,
    mock_start,
    mock_update,
    mock_get,
):
    row = _standard_row(
        meta={
            META_ENABLED_KEY: True,
            META_MAX_ATTEMPTS_KEY: 1,
            META_STATE_KEY: {
                "enabled": True,
                "max_attempts": 1,
                "batch_attempts": {"0": 1},
                "started_batch_indices": [0],
            },
            "listing_per_batch_limited_time_enabled": True,
            "listing_throttle": {
                "enabled": True,
                "completed": True,
                "total_batches": 1,
                "batch_index": 0,
            },
        }
    )
    mock_get.return_value = row
    mock_elig.return_value = {
        "eligible": True,
        "batch_index": 0,
        "retry_count": 1,
        "pdd_product_ids": ["p1"],
    }

    assert maybe_auto_start_batch_limited_time_retries(row, reason="maxed") is False
    mock_start.assert_not_called()
    # still records scan meta
    assert mock_update.called


@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.evaluate_batch_limited_time_retry_eligibility"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.is_standard_per_batch_lt_aggregate_pipeline",
    return_value=True,
)
def test_list_auto_retryable_batches_filters_attempts(_is_standard, mock_elig):
    row = _standard_row(
        meta={
            META_ENABLED_KEY: True,
            META_MAX_ATTEMPTS_KEY: 2,
            META_STATE_KEY: {
                "enabled": True,
                "max_attempts": 2,
                "batch_attempts": {"0": 2, "1": 0},
            },
            "listing_per_batch_limited_time_enabled": True,
            "listing_throttle": {
                "enabled": True,
                "completed": True,
                "total_batches": 2,
            },
        }
    )

    def _elig(_row, batch_index):
        if batch_index == 0:
            return {"eligible": True, "retry_count": 1, "pdd_product_ids": ["a"]}
        return {"eligible": True, "retry_count": 3, "pdd_product_ids": ["b", "c", "d"]}

    mock_elig.side_effect = _elig
    items = list_auto_retryable_batches(row)
    assert len(items) == 1
    assert items[0]["batch_index"] == 1
    assert items[0]["retry_count"] == 3

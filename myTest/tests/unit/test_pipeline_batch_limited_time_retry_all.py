"""pipeline_batch_limited_time_retry_all 单元测试。"""

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_batch_limited_time_retry_all.policy import (
    list_all_retryable_batches,
    start_all_batch_limited_time_retries,
)


def _row(**meta_extra):
    meta = {
        "listing_per_batch_limited_time_enabled": True,
        "listing_throttle": {
            "enabled": True,
            "completed": True,
            "total_batches": 3,
            "batch_index": 2,
        },
    }
    meta.update(meta_extra)
    return SimpleNamespace(
        pipeline_id="pipe_all",
        account_id="acc",
        current_step="waiting_activity",
        status="waiting_activity",
        meta=meta,
    )


@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.evaluate_batch_limited_time_retry_eligibility"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.is_standard_per_batch_lt_aggregate_pipeline",
    return_value=True,
)
def test_list_all_retryable_batches(_is_standard, mock_elig):
    row = _row()

    def _elig(_row, batch_index):
        if batch_index == 1:
            return {"eligible": False, "reason": "no_limited_time_retry_targets"}
        return {
            "eligible": True,
            "batch_index": batch_index,
            "retry_count": batch_index + 1,
            "pdd_product_ids": [f"p{batch_index}"],
        }

    mock_elig.side_effect = _elig
    items = list_all_retryable_batches(row)
    assert [x["batch_index"] for x in items] == [0, 2]
    assert items[0]["retry_count"] == 1


@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_all.policy.get_integrated_pipeline"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.build_batch_limited_time_retry_public_state",
    return_value={"phase": "limited_time", "limited_time_run_id": "run_a"},
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
def test_start_all_queues_after_first(
    _is_standard,
    mock_elig,
    mock_start,
    _public,
    mock_get,
):
    row = _row()
    mock_get.return_value = row

    def _elig(_row, batch_index):
        return {
            "eligible": True,
            "batch_index": batch_index,
            "retry_count": 2,
            "pdd_product_ids": [f"p{batch_index}a", f"p{batch_index}b"],
        }

    mock_elig.side_effect = _elig

    def _start(pipeline_id, *, batch_index):
        return {
            "pipeline_id": pipeline_id,
            "batch_index": batch_index,
            "retry_count": 2,
            "pdd_product_ids": [f"p{batch_index}a", f"p{batch_index}b"],
            "limited_time_run_id": "run_a" if batch_index == 0 else "",
            "queued": batch_index > 0,
            "batch_limited_time_retry": {"phase": "limited_time"},
        }

    mock_start.side_effect = _start
    result = start_all_batch_limited_time_retries("pipe_all")
    assert result["batch_count"] == 3
    assert result["retry_count"] == 6
    assert len(result["started_batches"]) == 1
    assert len(result["queued_batches"]) == 2
    assert mock_start.call_count == 3


@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_all.policy.get_integrated_pipeline"
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.is_standard_per_batch_lt_aggregate_pipeline",
    return_value=True,
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.evaluate_batch_limited_time_retry_eligibility",
    return_value={"eligible": False, "reason": "no_limited_time_retry_targets"},
)
def test_start_all_raises_when_no_targets(mock_elig, _is_standard, mock_get):
    row = _row()
    mock_get.return_value = row
    try:
        start_all_batch_limited_time_retries("pipe_all")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert str(exc) == "no_limited_time_retry_targets"

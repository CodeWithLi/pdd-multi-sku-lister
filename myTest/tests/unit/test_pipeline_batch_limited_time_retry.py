"""pipeline_batch_limited_time_retry_policy 单元测试。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from pdd_agent.api.services.pipeline_batch_limited_time_retry_policy import (
    evaluate_batch_limited_time_retry_eligibility,
    is_batch_limited_time_retry_run,
    is_pipeline_all_batches_complete,
    list_batch_limited_time_retry_targets,
    maybe_handle_batch_limited_time_retry_finished,
    start_batch_limited_time_retry,
)


def _row(**kwargs):
    defaults = {
        "pipeline_id": "pipe1",
        "account_id": "acc1",
        "status": "waiting_activity",
        "current_step": "waiting_activity",
        "demo_mode": False,
        "activity_delay_hours": 24.0,
        "pdd_product_ids": ["111"],
        "mapping_ids": ["m1"],
        "campaign_run_id": "camp1",
        "scheduled_activity_at": datetime.now() + timedelta(hours=24),
        "meta": {
            "listing_per_batch_limited_time_enabled": True,
            "std_per_batch_lt_agg_finalized": True,
        },
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.is_standard_per_batch_lt_aggregate_pipeline",
    return_value=True,
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_eligibility.is_pipeline_listing_batches_complete",
    return_value=True,
)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.list_batch_limited_time_retry_targets",
    return_value=[{"pdd_product_id": "111", "mapping_id": "m1", "listing_status": "success", "limited_time_status": "failed"}],
)
def test_evaluate_eligible(_targets, _complete, _std):
    result = evaluate_batch_limited_time_retry_eligibility(_row(), 0)
    assert result["eligible"] is True
    assert result["retry_count"] == 1


@patch(
    "pdd_agent.api.services.pipeline_batch_product_stage_tracker.list_pipeline_batch_product_stages",
)
def test_list_batch_limited_time_retry_targets(mock_list):
    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
        STAGE_FAILED,
        STAGE_SUCCESS,
    )

    mock_list.return_value = [
        {"listing_status": STAGE_SUCCESS, "limited_time_status": STAGE_FAILED, "pdd_product_id": "111"},
        {"listing_status": STAGE_SUCCESS, "limited_time_status": STAGE_SUCCESS, "pdd_product_id": "222"},
        {"listing_status": STAGE_FAILED, "limited_time_status": STAGE_FAILED, "pdd_product_id": "333"},
    ]
    targets = list_batch_limited_time_retry_targets(pipeline_id="pipe1", batch_index=0)
    assert len(targets) == 1
    assert targets[0]["pdd_product_id"] == "111"


def test_is_batch_limited_time_retry_run():
    row = _row(meta={"pipeline_batch_limited_time_retry": {"limited_time_run_id": "lt1"}})
    assert is_batch_limited_time_retry_run(row, "lt1") is True
    assert is_batch_limited_time_retry_run(row, "other") is False


@patch(
    "pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge.is_standard_per_batch_lt_pipeline",
    return_value=True,
)
def test_is_pipeline_all_batches_complete_listing_done(_std):
    row = SimpleNamespace(
        current_step="waiting_limited_time_per_batch",
        listing_run_id="lr1",
        meta={
            "listing_throttle": {
                "enabled": True,
                "batch_index": 18,
                "total_batches": 19,
            }
        },
    )
    assert is_pipeline_all_batches_complete(row) is True


@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy._enqueue_batch_limited_time_retry")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.evaluate_batch_limited_time_retry_eligibility")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.list_batch_limited_time_retry_targets")
def test_start_batch_retry(mock_targets, mock_eval, mock_enqueue, mock_get):
    mock_get.return_value = _row()
    mock_eval.return_value = {"eligible": True}
    mock_targets.return_value = [{"pdd_product_id": "111", "mapping_id": "m1"}]
    mock_enqueue.return_value = "lt_run_1"

    result = start_batch_limited_time_retry("pipe1", batch_index=0)
    assert result["limited_time_run_id"] == "lt_run_1"
    assert result["retry_count"] == 1
    mock_enqueue.assert_called_once()


@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy._save_batch_lt_retry_state")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.evaluate_batch_limited_time_retry_eligibility")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.list_batch_limited_time_retry_targets")
def test_start_batch_retry_queues_when_in_progress(mock_targets, mock_eval, mock_save, mock_get):
    row = _row(
        meta={
            "pipeline_batch_limited_time_retry": {
                "phase": "limited_time",
                "limited_time_run_id": "lt_running",
                "active_batch_index": 0,
                "pending_batch_indices": [],
            }
        }
    )
    mock_get.return_value = row
    mock_eval.return_value = {"eligible": True}
    mock_targets.return_value = [{"pdd_product_id": "222", "mapping_id": "m2"}]

    result = start_batch_limited_time_retry("pipe1", batch_index=1)
    assert result["queued"] is True
    assert result["limited_time_run_id"] == "lt_running"
    mock_save.assert_called_once()
    assert mock_save.call_args[0][1]["pending_batch_indices"] == [1]


@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy._start_next_pending_batch", return_value=False)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy.maybe_finalize_activity_after_batch_lt_retry",
    return_value=True,
)
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy._merge_limited_time_success_into_activity_pool")
@patch("pdd_agent.api.services.pipeline_batch_product_stage_tracker.record_limited_time_batch")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy._resolve_lt_success_for_batch")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.list_batch_limited_time_retry_targets")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.update_integrated_pipeline")
def test_handle_batch_retry_success_finalizes(
    _update,
    mock_get,
    mock_targets,
    mock_resolve,
    _record,
    mock_merge,
    _finalize,
    _next,
):
    row = _row(
        meta={
            "pipeline_batch_limited_time_retry": {
                "limited_time_run_id": "lt1",
                "active_batch_index": 0,
            }
        }
    )
    mock_get.return_value = row
    mock_targets.return_value = [{"pdd_product_id": "111", "mapping_id": "m1"}]
    mock_resolve.return_value = (["111"], ["m1"], [])
    mock_merge.return_value = (["111"], ["m1"], ["111"], ["m1"])

    handled = maybe_handle_batch_limited_time_retry_finished(
        row,
        run_id="lt1",
        success=True,
        result={"status": "success"},
        error="",
    )
    assert handled is True


@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy._start_next_pending_batch", return_value=False)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy.maybe_finalize_activity_after_batch_lt_retry",
    return_value=False,
)
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy._merge_limited_time_success_into_activity_pool")
@patch("pdd_agent.api.services.pipeline_batch_product_stage_tracker.record_limited_time_batch")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy._resolve_lt_success_for_batch")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.list_batch_limited_time_retry_targets")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_policy.update_integrated_pipeline")
def test_handle_batch_retry_success_revives_when_finalize_deferred(
    mock_update,
    mock_get,
    mock_targets,
    mock_resolve,
    _record,
    mock_merge,
    _finalize,
    _next,
):
    row = _row(
        status="failed",
        current_step="traffic_failed",
        meta={
            "pipeline_batch_limited_time_retry": {
                "limited_time_run_id": "lt1",
                "active_batch_index": 0,
            },
            "batch_lt_retry_restore_status": "failed",
            "batch_lt_retry_restore_step": "traffic_failed",
        },
    )
    mock_get.return_value = row
    mock_targets.return_value = [{"pdd_product_id": "111", "mapping_id": "m1"}]
    mock_resolve.return_value = (["111"], ["m1"], [])
    mock_merge.return_value = (["111"], ["m1"], ["111"], ["m1"])

    handled = maybe_handle_batch_limited_time_retry_finished(
        row,
        run_id="lt1",
        success=True,
        result={"status": "success"},
        error="",
    )
    assert handled is True
    revive_calls = [
        call
        for call in mock_update.call_args_list
        if call.kwargs.get("status") == "waiting_activity"
        or (call.kwargs.get("meta_patch") or {}).get("batch_lt_retry_revived_activity")
    ]
    assert revive_calls

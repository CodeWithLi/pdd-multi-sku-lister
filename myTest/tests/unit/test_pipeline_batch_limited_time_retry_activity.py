"""pipeline_batch_limited_time_retry_activity_policy 单元测试。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy import (
    maybe_finalize_activity_after_batch_lt_retry,
    record_batch_lt_retry_success_finished_at,
)


def _row(**kwargs):
    defaults = {
        "pipeline_id": "pipe1",
        "account_id": "acc1",
        "status": "failed",
        "current_step": "limited_time_failed",
        "demo_mode": False,
        "activity_delay_hours": 24.0,
        "campaign_run_id": "",
        "meta": {
            "pipeline_batch_lt_retry_activity_defer": {
                "awaiting_reschedule": True,
                "limited_time_finished_at": datetime.now().isoformat(),
            }
        },
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy.update_integrated_pipeline")
def test_record_batch_lt_retry_success_finished_at(mock_update):
    row = _row()
    ts = datetime(2026, 7, 12, 14, 0, 0)
    record_batch_lt_retry_success_finished_at(row, finished_at=ts)
    mock_update.assert_called_once()
    meta_patch = mock_update.call_args.kwargs["meta_patch"]
    defer = meta_patch["pipeline_batch_lt_retry_activity_defer"]
    assert defer["limited_time_finished_at"] == ts.isoformat()
    assert defer["awaiting_reschedule"] is True


@patch("pdd_agent.api.services.pipeline_service._schedule_pipeline_campaign")
@patch(
    "pdd_agent.api.services.pipeline_activity_limited_time_success.resolve_activity_product_ids_for_row",
    return_value=(["111"], ["m1"]),
)
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy.is_batch_lt_retry_in_progress", return_value=False)
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy.update_integrated_pipeline")
def test_finalize_creates_activity_when_no_campaign(
    mock_update,
    _in_progress,
    _resolve,
    mock_schedule,
):
    row = _row(campaign_run_id="")
    assert maybe_finalize_activity_after_batch_lt_retry(row) is True
    mock_schedule.assert_called_once()


@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy.update_queued_task_schedule", return_value=True)
@patch(
    "pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy.get_queue_task_by_run_id",
    return_value=SimpleNamespace(status="queued", task_id="task1"),
)
@patch(
    "pdd_agent.api.services.pipeline_activity_limited_time_success.resolve_activity_product_ids_for_row",
    return_value=(["111", "222"], ["m1", "m2"]),
)
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy.is_batch_lt_retry_in_progress", return_value=False)
@patch("pdd_agent.api.services.pipeline_batch_limited_time_retry_activity_policy.update_integrated_pipeline")
def test_finalize_reschedules_existing_campaign(
    mock_update,
    _in_progress,
    _resolve,
    _task,
    mock_reschedule,
):
    row = _row(
        status="waiting_activity",
        current_step="waiting_activity",
        campaign_run_id="camp1",
        scheduled_activity_at=datetime.now() + timedelta(hours=2),
    )
    assert maybe_finalize_activity_after_batch_lt_retry(row) is True
    mock_reschedule.assert_called_once()

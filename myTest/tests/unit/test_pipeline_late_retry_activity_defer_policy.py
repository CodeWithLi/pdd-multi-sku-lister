"""pipeline_late_retry_activity_defer_policy 单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_late_retry_activity_defer_policy import (
    augment_late_retry_eligibility,
    is_late_retry_batch_in_progress,
    maybe_defer_activity_task_execution,
    maybe_reschedule_activity_after_late_retry_batch,
    record_late_retry_listing_finished_at,
    resolve_activity_scheduled_at_from_anchor,
    should_defer_activity_for_pipeline,
)


def _pipeline(**overrides):
    deadline = overrides.pop("scheduled_activity_at", None) or (datetime.now() + timedelta(hours=20))
    meta = dict(overrides.pop("meta", {}) or {})
    return SimpleNamespace(
        pipeline_id="pipe_defer",
        account_id="store_A",
        status="waiting_activity",
        current_step="waiting_activity",
        scheduled_activity_at=deadline,
        campaign_run_id="camp_run_1",
        demo_mode=True,
        activity_delay_hours=24.0,
        pdd_product_ids=["111"],
        mapping_ids=["m1"],
        meta=meta,
        **overrides,
    )


def test_resolve_activity_scheduled_at_from_anchor_demo_mode():
    anchor = datetime(2026, 7, 7, 10, 0, 0)
    scheduled = resolve_activity_scheduled_at_from_anchor(
        anchor=anchor,
        demo_mode=True,
        activity_delay_hours=24.0,
        jitter_max_seconds=0,
    )
    assert scheduled > anchor


@patch("pdd_agent.api.services.pipeline_late_retry_policy.late_retry_state")
def test_is_late_retry_batch_in_progress(mock_state):
    row = _pipeline()
    mock_state.return_value = {"phase": "listing"}
    assert is_late_retry_batch_in_progress(row) is True


def test_should_defer_when_late_retry_listing():
    row = _pipeline()
    with patch(
        "pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.is_late_retry_batch_in_progress",
        return_value=True,
    ):
        ok, reason = should_defer_activity_for_pipeline(row)
    assert ok is True
    assert "补跑" in reason


@patch("pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.requeue_running_task", return_value=True)
@patch("pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.update_integrated_pipeline")
@patch(
    "pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.is_late_retry_batch_in_progress",
    return_value=True,
)
def test_maybe_defer_activity_task_execution(mock_in_progress, mock_update, mock_requeue):
    row = _pipeline()
    assert maybe_defer_activity_task_execution(row, task_id="t1", run_id="camp_run_1") is True
    mock_requeue.assert_called_once()


@patch("pdd_agent.api.services.pipeline_late_retry_policy.list_failed_selectors", return_value=["A/第一套图/x"])
def test_augment_eligibility_allows_past_deadline(mock_failed):
    row = _pipeline(scheduled_activity_at=datetime.now() - timedelta(hours=1))
    out = augment_late_retry_eligibility(row, {"eligible": False, "reason": "activity_deadline_passed"})
    assert out["eligible"] is True
    assert out["failed_count"] == 1


@patch("pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.update_integrated_pipeline")
def test_record_late_retry_listing_finished_at(mock_update):
    row = _pipeline()
    ts = datetime(2026, 7, 7, 12, 0, 0)
    record_late_retry_listing_finished_at(row, finished_at=ts)
    mock_update.assert_called_once()
    patch_meta = mock_update.call_args.kwargs["meta_patch"]["pipeline_late_retry_activity_defer"]
    assert patch_meta["listing_finished_at"] == ts.isoformat()
    assert patch_meta["awaiting_reschedule"] is True


@patch("pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.update_queued_task_schedule", return_value=True)
@patch("pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.get_queue_task_by_run_id")
@patch(
    "pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.is_late_retry_batch_in_progress",
    return_value=False,
)
def test_reschedule_after_late_retry_batch(mock_in_progress, mock_get_task, mock_update_schedule, mock_update_pipe):
    anchor = datetime.now() - timedelta(hours=2)
    row = _pipeline(
        meta={
            "pipeline_late_retry_activity_defer": {
                "awaiting_reschedule": True,
                "listing_finished_at": anchor.isoformat(),
            }
        }
    )
    task = MagicMock()
    task.task_id = "task_1"
    task.status = "queued"
    mock_get_task.return_value = task

    ok = maybe_reschedule_activity_after_late_retry_batch(row)
    assert ok is True
    mock_update_schedule.assert_called_once()
    mock_update_pipe.assert_called()

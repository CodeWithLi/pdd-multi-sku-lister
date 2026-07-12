"""分批上架 — 失败后继续下一批。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_listing_batch_continue import (
    has_remaining_listing_batch,
    is_listing_batch_failure_continuing,
    maybe_continue_listing_batch_after_failure,
)


def _row(*, batch_index: int = 0, total_batches: int = 2, current_step: str = "listing_queued"):
    return SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="store_A",
        status="running",
        current_step=current_step,
        meta={
            "listing_throttle": {
                "enabled": True,
                "batch_index": batch_index,
                "total_batches": total_batches,
                "batches": [[f"B{i}"] for i in range(total_batches)],
                "interval_minutes": 5,
                "listing_payload_base": {},
                "accumulated_pdd_ids": [],
                "accumulated_mapping_ids": [],
            }
        },
    )


def test_has_remaining_listing_batch():
    assert has_remaining_listing_batch(_row(batch_index=0, total_batches=2)) is True
    assert has_remaining_listing_batch(_row(batch_index=1, total_batches=2)) is False


@patch("pdd_agent.api.services.pipeline_listing_batch_continue.get_integrated_pipeline")
def test_is_listing_batch_failure_continuing(mock_get):
    row = _row(current_step="waiting_listing_batch_2")
    mock_get.return_value = row
    assert is_listing_batch_failure_continuing("pipe_1") is True


@patch("pdd_agent.api.services.pipeline_listing_batch_continue.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_listing_batch_continue.schedule_next_listing_batch_after_finish")
@patch("pdd_agent.api.services.pipeline_listing_batch_continue.get_integrated_pipeline")
def test_maybe_continue_after_failure_schedules_next_batch(
    mock_get,
    mock_schedule,
    mock_update,
):
    row = _row(batch_index=0, total_batches=2)
    mock_get.return_value = row
    mock_schedule.return_value = True

    handled = maybe_continue_listing_batch_after_failure(
        row,
        run_id="run_1",
        result={"results": [{"status": "retryable", "listing_label": "BD004A/第一套图"}]},
        error="0/1 listed",
    )

    assert handled is True
    mock_schedule.assert_called_once()
    mock_update.assert_called()
    assert mock_update.call_args.kwargs.get("status") == "running"


@patch("pdd_agent.api.services.pipeline_listing_batch_continue.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_listing_batch_continue.schedule_next_listing_batch_after_finish")
@patch("pdd_agent.api.services.pipeline_listing_batch_continue.get_integrated_pipeline")
def test_maybe_continue_after_empty_success_batch_schedules_next(
    mock_get,
    mock_schedule,
    mock_update,
):
    row = _row(batch_index=0, total_batches=3)
    mock_get.return_value = row
    mock_schedule.return_value = True

    handled = maybe_continue_listing_batch_after_failure(
        row,
        run_id="run_empty",
        result={"results": [{"status": "listed", "listing_label": "BD004A/第一套图"}]},
        error="",
    )

    assert handled is True
    mock_schedule.assert_called_once()


@patch("pdd_agent.api.services.pipeline_listing_batch_continue.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_listing_batch_continue.schedule_next_listing_batch_after_finish")
@patch(
    "pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge.record_skipped_limited_time_batch_for_empty_listing"
)
@patch("pdd_agent.api.services.pipeline_listing_batch_continue.get_integrated_pipeline")
def test_maybe_continue_empty_batch_records_skipped_lt_before_next(
    mock_get,
    mock_record_skipped,
    mock_schedule,
    mock_update,
):
    row = _row(batch_index=12, total_batches=19)
    mock_get.return_value = row
    mock_record_skipped.return_value = True
    mock_schedule.return_value = True

    handled = maybe_continue_listing_batch_after_failure(
        row,
        run_id="run_empty",
        result={"results": []},
        error="本批无成功上架商品",
    )

    assert handled is True
    mock_record_skipped.assert_called_once()
    mock_schedule.assert_called_once()


@patch("pdd_agent.api.services.pipeline_listing_batch_continue.schedule_next_listing_batch_after_finish")
def test_maybe_continue_returns_false_on_last_batch(mock_schedule):
    row = _row(batch_index=1, total_batches=2)
    assert (
        maybe_continue_listing_batch_after_failure(
            row,
            run_id="run_2",
            result={"results": []},
            error="failed",
        )
        is False
    )
    mock_schedule.assert_not_called()

"""pipeline_late_retry_policy 单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pdd_agent.api.services.pipeline_late_retry_policy import (
    PHASE_EXPIRED,
    PHASE_LIMITED_TIME,
    PHASE_LISTING,
    evaluate_late_retry_eligibility,
    is_late_retry_limited_time_run,
    is_late_retry_listing_run,
    maybe_handle_late_retry_listing_finished,
    maybe_handle_late_retry_limited_time_finished,
    resolve_campaign_pdd_ids_at_execution,
    start_late_retry_failed,
)


def _waiting_pipeline(**overrides):
    deadline = overrides.pop("scheduled_activity_at", None) or (datetime.now() + timedelta(hours=20))
    meta = {
        "activity_pdd_product_ids": ["111", "222"],
        "limited_time_success_pdd_product_ids": ["111", "222"],
    }
    meta.update(overrides.pop("meta", {}) or {})
    return SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="store_A",
        status="waiting_activity",
        current_step="waiting_activity",
        scheduled_activity_at=deadline,
        pdd_product_ids=["111", "222"],
        mapping_ids=["m1", "m2"],
        meta=meta,
        **overrides,
    )


@patch("pdd_agent.api.services.pipeline_late_retry_policy.list_failed_selectors", return_value=["BD001/第一套图/A1"])
def test_evaluate_eligible_when_waiting_activity(mock_failed):
    row = _waiting_pipeline()
    out = evaluate_late_retry_eligibility(row)
    assert out["eligible"] is True
    assert out["failed_count"] == 1


@patch("pdd_agent.api.services.pipeline_late_retry_policy.list_failed_selectors", return_value=["BD001/第一套图/A1"])
def test_evaluate_reject_when_deadline_passed_without_defer(mock_failed):
    row = _waiting_pipeline(
        scheduled_activity_at=datetime.now() - timedelta(minutes=5),
        meta={"pipeline_late_retry_activity_defer_enabled": False},
    )
    out = evaluate_late_retry_eligibility(row)
    assert out["eligible"] is False
    assert out["reason"] == "activity_deadline_passed"


@patch("pdd_agent.api.services.pipeline_late_retry_policy.list_failed_selectors", return_value=["BD001/第一套图/A1"])
def test_evaluate_eligible_past_deadline_with_defer(mock_failed):
    row = _waiting_pipeline(scheduled_activity_at=datetime.now() - timedelta(minutes=5))
    out = evaluate_late_retry_eligibility(row)
    assert out["eligible"] is True


@patch("pdd_agent.api.services.pipeline_late_retry_policy.list_failed_selectors", return_value=["BD001/第一套图/A1"])
def test_evaluate_reject_insufficient_buffer_without_defer(mock_failed):
    row = _waiting_pipeline(
        scheduled_activity_at=datetime.now() + timedelta(minutes=10),
        meta={"pipeline_late_retry_activity_defer_enabled": False},
    )
    out = evaluate_late_retry_eligibility(row)
    assert out["eligible"] is False
    assert out["reason"] == "insufficient_time_before_activity"


def test_is_late_retry_run_helpers():
    row = _waiting_pipeline(
        meta={
            "pipeline_late_retry": {
                "listing_run_id": "lr_1",
                "limited_time_run_id": "lt_1",
            }
        }
    )
    assert is_late_retry_listing_run(row, "lr_1") is True
    assert is_late_retry_limited_time_run(row, "lt_1") is True
    assert is_late_retry_listing_run(row, "other") is False


@patch("pdd_agent.api.services.pipeline_late_retry_policy._enqueue_late_retry_limited_time", return_value="lt_new")
@patch("pdd_agent.api.services.pipeline_late_retry_policy.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_late_retry_policy._classify_listing_outcome")
def test_listing_finished_enqueues_limited_time(mock_classify, mock_update, mock_enqueue_lt):
    row = _waiting_pipeline(
        meta={
            "pipeline_late_retry": {
                "listing_run_id": "lr_1",
                "selectors": ["BD001/第一套图/A1"],
            }
        }
    )
    mock_classify.return_value = (["BD001/第一套图/A1"], [], ["333"], ["m3"])

    handled = maybe_handle_late_retry_listing_finished(
        row,
        run_id="lr_1",
        success=True,
        result={"results": []},
        error="",
    )
    assert handled is True
    mock_enqueue_lt.assert_called_once_with(row, pdd_ids=["333"], mapping_ids=["m3"])


@patch(
    "pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.maybe_reschedule_activity_after_late_retry_batch"
)
@patch("pdd_agent.api.services.pipeline_late_retry_activity_defer_policy.record_late_retry_listing_finished_at")
@patch("pdd_agent.api.services.pipeline_late_retry_policy.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_late_retry_policy._classify_listing_outcome")
def test_listing_finished_no_pdd_ids_does_not_reschedule(
    mock_classify,
    mock_update,
    mock_record_anchor,
    mock_reschedule,
):
    row = _waiting_pipeline(
        meta={
            "pipeline_late_retry": {
                "listing_run_id": "lr_1",
                "selectors": ["BD001/第一套图/A1"],
            }
        }
    )
    mock_classify.return_value = ([], ["BD001/第一套图/A1"], [], [])

    handled = maybe_handle_late_retry_listing_finished(
        row,
        run_id="lr_1",
        success=True,
        result={"results": []},
        error="",
    )
    assert handled is True
    mock_record_anchor.assert_not_called()
    mock_reschedule.assert_not_called()


@patch("pdd_agent.api.services.pipeline_late_retry_policy._merge_limited_time_success_into_activity_pool")
@patch("pdd_agent.api.services.pipeline_late_retry_policy.update_integrated_pipeline")
def test_limited_time_finished_merges_pool(mock_update, mock_merge):
    row = _waiting_pipeline(
        meta={
            "pipeline_late_retry": {
                "limited_time_run_id": "lt_1",
                "selectors": ["BD001/第一套图/A1"],
                "failed_selectors": [],
            }
        }
    )
    mock_merge.return_value = (["111", "222", "333"], ["m1", "m2", "m3"])

    handled = maybe_handle_late_retry_limited_time_finished(
        row,
        run_id="lt_1",
        success=True,
        result={"results": [{"status": "success", "step": "activity_created"}]},
        error="",
    )
    assert handled is True
    mock_merge.assert_called_once()


@patch("pdd_agent.api.services.pipeline_late_retry_policy.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_late_retry_policy.finalize_late_retry_before_activity_execution")
def test_resolve_campaign_reads_pipeline_pool(mock_finalize, mock_get):
    row = _waiting_pipeline()
    mock_get.return_value = row

    with patch(
        "pdd_agent.api.services.pipeline_activity_limited_time_success.resolve_activity_product_ids_for_row",
        return_value=(["111", "222", "333"], ["m1", "m2", "m3"]),
    ):
        ids = resolve_campaign_pdd_ids_at_execution(
            pipeline_id="pipe_1",
            payload_pdd_ids=["111", "222"],
        )
    assert ids == ["111", "222", "333"]
    mock_finalize.assert_called_once_with("pipe_1")


@patch("pdd_agent.api.services.pipeline_late_retry_policy.enqueue_task")
@patch("pdd_agent.api.services.pipeline_late_retry_policy.create_listing_run", return_value="lr_new")
@patch("pdd_agent.api.services.pipeline_late_retry_policy.TaskRunStore")
@patch("pdd_agent.api.services.pipeline_late_retry_policy.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_late_retry_policy.evaluate_late_retry_eligibility")
def test_start_late_retry_queues_listing(mock_eval, mock_get, mock_store_cls, mock_create_run, mock_enqueue):
    row = _waiting_pipeline()
    mock_get.return_value = row
    mock_eval.return_value = {
        "eligible": True,
        "failed_selectors": ["BD001/第一套图/A1"],
        "minutes_remaining": 1200,
    }
    mock_store_cls.return_value = MagicMock()

    out = start_late_retry_failed("pipe_1")
    assert out["listing_run_id"] == "lr_new"
    assert out["selector_count"] == 1
    mock_enqueue.assert_called_once()
    payload = mock_enqueue.call_args.kwargs["payload"]
    assert payload.get("pipeline_late_retry") is True
    assert payload.get("pipeline_id") == "pipe_1"

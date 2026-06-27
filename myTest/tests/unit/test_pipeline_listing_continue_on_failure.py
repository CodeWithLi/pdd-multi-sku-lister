"""上架失败不中断：分批累计 / 多店铺串行。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_service import _continue_pipeline_after_listing, _on_listing_finished


def _throttle_row(*, batch_index: int = 1, total_batches: int = 2, accumulated: list[str] | None = None):
    return SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="store_A",
        status="running",
        current_step="listing_queued",
        demo_mode=False,
        activity_delay_hours=24.0,
        meta={
            "auto_limited_time_setup": True,
            "listing_throttle": {
                "enabled": True,
                "batch_index": batch_index,
                "total_batches": total_batches,
                "batches": [["A1"], ["B1"]],
                "interval_minutes": 5,
                "listing_payload_base": {},
                "accumulated_pdd_ids": list(accumulated or []),
                "accumulated_mapping_ids": [],
            },
        },
    )


@patch("pdd_agent.api.services.pipeline_service._enqueue_pipeline_limited_time")
@patch("pdd_agent.api.services.pipeline_service._pipeline_auto_limited_time", return_value=True)
@patch("pdd_agent.api.services.pipeline_service._summarize_run_message", return_value="batch failed")
@patch("pdd_agent.api.services.pipeline_service.get_integrated_pipeline")
def test_continue_with_accumulated_after_last_batch_failure(
    mock_get,
    _mock_summary,
    _mock_auto_lt,
    mock_enqueue_lt,
):
    row = _throttle_row(batch_index=1, total_batches=2, accumulated=["pdd_from_batch1"])
    mock_get.return_value = row

    continued = _continue_pipeline_after_listing(
        row,
        run_id="run_last",
        result={"results": [{"status": "failed", "listing_label": "B1/第一套图"}]},
        pdd_ids=[],
        mapping_ids=[],
        error_hint="本批全部失败",
    )

    assert continued is True
    mock_enqueue_lt.assert_called_once()
    call_kwargs = mock_enqueue_lt.call_args.kwargs
    assert call_kwargs["pdd_ids"] == ["pdd_from_batch1"]


@patch("pdd_agent.api.services.pipeline_service._continue_pipeline_after_listing", return_value=True)
@patch(
    "pdd_agent.api.services.pipeline_listing_batch_continue.maybe_continue_listing_batch_after_failure",
    return_value=False,
)
@patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline")
def test_on_listing_finished_failure_continues_with_accumulated(
    mock_update,
    _mock_batch_continue,
    mock_continue,
):
    row = _throttle_row(batch_index=1, accumulated=["pdd_1"])

    _on_listing_finished(
        row,
        run_id="run_x",
        success=False,
        result={"results": []},
        error="0/1 listed",
    )

    mock_continue.assert_called_once()
    mock_update.assert_not_called()


@patch("pdd_agent.api.services.pipeline_service._try_wecom_pipeline_failed")
@patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_service._continue_pipeline_after_listing", return_value=False)
@patch(
    "pdd_agent.api.services.pipeline_listing_batch_continue.maybe_continue_listing_batch_after_failure",
    return_value=False,
)
def test_on_listing_finished_failure_marks_failed_when_nothing_to_continue(
    _mock_batch_continue,
    _mock_continue,
    mock_update,
    _mock_wecom,
):
    row = _throttle_row(batch_index=1, accumulated=[])

    _on_listing_finished(
        row,
        run_id="run_x",
        success=False,
        result={"results": []},
        error="全部失败",
    )

    mock_update.assert_called_once()
    assert mock_update.call_args.kwargs.get("status") == "failed"

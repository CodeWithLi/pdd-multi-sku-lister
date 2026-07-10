"""标准分批限时限量购 — 跨批聚合进度。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator import (
    is_standard_per_batch_lt_pipeline,
    maybe_finalize_after_all_batches,
    record_limited_time_batch_finished,
    restore_intermediate_lt_progress_meta,
    should_absorb_limited_time_task_failure,
)


def _row(*, meta: dict | None = None, **kwargs):
    defaults = {
        "pipeline_id": "pipe_1",
        "account_id": "store_A",
        "meta": meta or {},
        "pdd_product_ids": ["pdd_1"],
        "mapping_ids": ["map_1"],
        "current_step": "waiting_limited_time_per_batch",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _throttle_meta(*, batch_index: int = 2, total_batches: int = 3, awaiting_final: bool = True):
    return {
        "listing_throttle": {
            "enabled": True,
            "total_batches": total_batches,
            "batch_index": batch_index,
            "batches": [
                ["A/第一套图/A1"],
                ["B/第一套图/B1"],
                ["C/第一套图/C1"],
            ],
            "completed": awaiting_final,
        },
        "listing_per_batch_limited_time_enabled": True,
        "auto_limited_time_setup": True,
        "limited_time_run_id": "lt_final",
        "listing_per_batch_limited_time": {
            "enabled": True,
            "last_batch_index": batch_index,
            "awaiting_final_activity": awaiting_final,
        },
        "std_per_batch_lt_agg_pdd_ids": ["pdd_prev"],
        "std_per_batch_lt_agg_mapping_ids": ["map_prev"],
        "std_per_batch_lt_agg_batch_count": 2,
        "std_per_batch_lt_agg_batch_log": [
            {"batch_index": 0, "batch_success_count": 1},
            {"batch_index": 1, "batch_success_count": 1},
        ],
    }


def test_is_standard_per_batch_lt_pipeline():
    row = _row(meta=_throttle_meta())
    assert is_standard_per_batch_lt_pipeline(row) is True

    row_ltta = _row(meta={**_throttle_meta(), "listing_per_batch_lt_traffic_activity_enabled": True})
    assert is_standard_per_batch_lt_pipeline(row_ltta) is False


@patch("pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator.record_limited_time_batch")
@patch(
    "pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator._resolve_lt_success_products",
    return_value=(["pdd_1"], ["map_1"]),
)
def test_record_limited_time_batch_finished_accumulates(mock_resolve, mock_record_lt, mock_update):
    row = _row(meta=_throttle_meta(batch_index=2, awaiting_final=True))
    refreshed = record_limited_time_batch_finished(
        row,
        run_id="lt_final",
        success=False,
        result={"activity_created": [{"pdd_product_id": "pdd_1"}]},
        error="最后一批失败",
    )
    assert refreshed is row
    mock_record_lt.assert_called_once()
    mock_update.assert_called_once()
    patch_meta = mock_update.call_args.kwargs["meta_patch"]
    assert "pdd_prev" in patch_meta["std_per_batch_lt_agg_pdd_ids"]
    assert "pdd_1" in patch_meta["std_per_batch_lt_agg_pdd_ids"]


@patch("pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator.update_integrated_pipeline")
def test_restore_intermediate_clears_outcome(mock_update):
    row = _row(
        meta={
            **_throttle_meta(batch_index=0, awaiting_final=False),
            "listing_per_batch_limited_time": {
                "enabled": True,
                "last_batch_index": 0,
                "awaiting_final_activity": False,
                "pending": {"next_batch_index": 1, "interval_minutes": 2},
            },
            "limited_time_outcome": "failed",
            "limited_time_skip_reason": "中间批失败",
        }
    )
    restore_intermediate_lt_progress_meta(row)
    mock_update.assert_called_once()
    patch_meta = mock_update.call_args.kwargs["meta_patch"]
    assert patch_meta.get("limited_time_outcome") == ""


@patch("pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator.update_integrated_pipeline")
def test_finalize_schedules_activity_when_accumulated_success_exists(mock_update, mock_get):
    row = _row(meta=_throttle_meta())
    mock_get.return_value = row
    schedule_fn = MagicMock()
    advance_fn = MagicMock()

    handled = maybe_finalize_after_all_batches(
        row,
        run_id="lt_final",
        success=False,
        result={},
        error="最后一批限时失败",
        schedule_activity_fn=schedule_fn,
        advance_store_sequential_fn=advance_fn,
        summarize_run_message_fn=lambda _rid: "summary",
    )

    assert handled is True
    schedule_fn.assert_called_once()
    advance_fn.assert_called_once()
    update_kwargs = mock_update.call_args.kwargs
    assert update_kwargs["current_step"] == "limited_time_success_continue"
    assert update_kwargs["meta_patch"]["std_per_batch_lt_agg_finalized"] is True
    assert update_kwargs["meta_patch"]["limited_time_outcome"] == "partial_success"


@patch("pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator.update_integrated_pipeline")
def test_finalize_returns_false_when_no_accumulated_success(mock_update):
    row = _row(
        meta={
            **_throttle_meta(),
            "std_per_batch_lt_agg_pdd_ids": [],
            "std_per_batch_lt_agg_mapping_ids": [],
        }
    )
    handled = maybe_finalize_after_all_batches(
        row,
        run_id="lt_final",
        success=False,
        result={},
        error="全部失败",
        schedule_activity_fn=MagicMock(),
        advance_store_sequential_fn=MagicMock(),
        summarize_run_message_fn=lambda _rid: "",
    )
    assert handled is False
    mock_update.assert_not_called()


def test_should_absorb_final_batch_failure_when_accumulated():
    row = _row(meta=_throttle_meta())
    assert should_absorb_limited_time_task_failure(row, run_id="lt_final") is True


def test_should_absorb_middle_batch_failure():
    row = _row(
        meta={
            **_throttle_meta(batch_index=0, awaiting_final=False),
            "listing_per_batch_limited_time": {
                "enabled": True,
                "last_batch_index": 0,
                "awaiting_final_activity": False,
                "pending": {"next_batch_index": 1},
            },
            "limited_time_run_id": "lt_mid",
        }
    )
    assert should_absorb_limited_time_task_failure(row, run_id="lt_mid") is True


@patch("pdd_agent.api.services.pipeline_batch_product_stage_tracker.record_activity_for_pipeline")
def test_record_campaign_finished_writes_activity(mock_record):
    row = _row(
        meta={
            **_throttle_meta(),
            "activity_ids": ["20981", "21365"],
            "campaign_activity_index": 0,
            "limited_time_success_pdd_product_ids": ["pdd_prev"],
        },
        activity_id="20981",
        pdd_product_ids=["pdd_prev"],
    )
    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator import record_campaign_finished

    record_campaign_finished(
        row,
        run_id="camp_run_1",
        success=True,
        result={"results": []},
        error="",
    )
    mock_record.assert_called_once()
    kwargs = mock_record.call_args.kwargs
    assert kwargs["activity_index"] == 0
    assert kwargs["activity_id"] == "20981"
    assert kwargs["success"] is True
    assert "pdd_prev" in kwargs["target_pdd_ids"]


@patch("pdd_agent.api.services.pipeline_batch_product_stage_tracker.record_promotion_for_pipeline")
def test_record_traffic_finished_writes_promotion(mock_record):
    row = _row(
        meta={
            **_throttle_meta(),
            "limited_time_success_pdd_product_ids": ["pdd_prev"],
        },
        traffic_run_id="traffic_run_1",
        auto_promotion=True,
        pdd_product_ids=["pdd_prev"],
    )
    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.orchestrator import record_traffic_finished

    record_traffic_finished(
        row,
        run_id="traffic_run_1",
        success=True,
        error="",
        result={"results": [{"status": "success"}]},
    )
    mock_record.assert_called_once()
    kwargs = mock_record.call_args.kwargs
    assert kwargs["success"] is True
    assert kwargs["skipped"] is False
    assert "pdd_prev" in kwargs["target_pdd_ids"]

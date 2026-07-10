"""活动 / 推广按商品数分批。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator import (
    _build_initial_state,
    _chunk_products,
    activity_traffic_batch_meta_patch,
    is_activity_traffic_batch_active,
    is_activity_traffic_batch_enabled,
    maybe_handle_campaign_finished,
    maybe_handle_traffic_finished,
    maybe_start_after_limited_time,
)
from pdd_agent.api.services.pipeline_activity_traffic_batch.constants import (
    META_ENABLED_KEY,
    META_STATE_KEY,
    PHASE_ACTIVITY,
    PHASE_TRAFFIC,
)


def _row(*, meta: dict | None = None, **kwargs):
    defaults = {
        "pipeline_id": "pipe_atb",
        "account_id": "store_A",
        "meta": meta or {},
        "activity_id": "20981",
        "activity_ids": ["20981", "21365"],
        "auto_promotion": True,
        "demo_mode": False,
        "activity_delay_hours": 24.0,
        "campaign_run_id": "camp_1",
        "traffic_run_id": "traffic_1",
        "current_step": "waiting_activity",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _enabled_meta(*, batch_size: int = 3, state: dict | None = None):
    meta = activity_traffic_batch_meta_patch(enabled=True, batch_size=batch_size)
    if state is not None:
        meta[META_STATE_KEY] = state
    return meta


def test_meta_patch_and_enabled():
    patch = activity_traffic_batch_meta_patch(enabled=True, batch_size=10)
    assert patch[META_ENABLED_KEY] is True
    assert patch["activity_traffic_batch_size"] == 10
    row = _row(meta=patch)
    assert is_activity_traffic_batch_enabled(row) is True
    assert is_activity_traffic_batch_active(row) is False


def test_chunk_products_splits_by_batch_size():
    row = _row()
    pdd_ids = [f"pdd_{i}" for i in range(7)]
    mapping_ids = [f"map_{i}" for i in range(7)]
    chunks = _chunk_products(row, pdd_ids=pdd_ids, mapping_ids=mapping_ids, batch_size=3)
    assert len(chunks) == 3
    assert [len(c["pdd_product_ids"]) for c in chunks] == [3, 3, 1]
    assert chunks[0]["mapping_ids"] == ["map_0", "map_1", "map_2"]


def test_build_initial_state():
    row = _row(meta=_enabled_meta(batch_size=2))
    state = _build_initial_state(
        row,
        pdd_ids=["p1", "p2", "p3", "p4", "p5"],
        mapping_ids=["m1", "m2", "m3", "m4", "m5"],
    )
    assert state["enabled"] is True
    assert state["batch_size"] == 2
    assert state["total_chunks"] == 3
    assert state["chunk_index"] == 0
    assert state["activity_index"] == 0
    assert state["phase"] == PHASE_ACTIVITY


@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator._schedule_campaign_for_chunk")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.get_integrated_pipeline")
@patch(
    "pdd_agent.api.services.pipeline_activity_limited_time_success.resolve_activity_product_ids_for_row",
    return_value=(["p1", "p2", "p3"], ["m1", "m2", "m3"]),
)
@patch(
    "pdd_agent.api.services.pipeline_service.resolve_activity_scheduled_at",
    return_value=datetime(2026, 7, 10, 12, 0, 0),
)
@patch(
    "pdd_agent.api.services.pipeline_service._resolve_activity_delay",
    return_value=__import__("datetime").timedelta(hours=24),
)
def test_maybe_start_after_limited_time_initializes(
    mock_delay,
    mock_scheduled_at,
    mock_resolve_products,
    mock_get,
    mock_update,
    mock_schedule_campaign,
):
    row = _row(meta=_enabled_meta(batch_size=2))
    mock_get.return_value = row

    handled = maybe_start_after_limited_time(row)

    assert handled is True
    mock_update.assert_called()
    mock_schedule_campaign.assert_called_once()
    schedule_kwargs = mock_schedule_campaign.call_args.kwargs
    assert schedule_kwargs["activity_index"] == 0
    assert len(schedule_kwargs["chunk"]["pdd_product_ids"]) == 2


def test_maybe_start_skips_when_conflicts_with_ltta():
    row = _row(
        meta={
            **_enabled_meta(),
            "listing_per_batch_lt_traffic_activity_enabled": True,
        }
    )
    assert maybe_start_after_limited_time(row) is False


@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator._schedule_campaign_for_chunk")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.get_integrated_pipeline")
@patch(
    "pdd_agent.api.services.pipeline_service._campaign_run_already_handled",
    return_value=False,
)
@patch(
    "pdd_agent.api.services.pipeline_service._pipeline_activity_ids",
    return_value=["20981", "21365"],
)
@patch(
    "pdd_agent.api.services.pipeline_service._campaign_activity_index",
    return_value=0,
)
@patch(
    "pdd_agent.api.services.pipeline_service._summarize_run_message",
    return_value="ok",
)
def test_campaign_finished_schedules_next_activity(
    mock_summary,
    mock_activity_index,
    mock_activity_ids,
    mock_already_handled,
    mock_get,
    mock_update,
    mock_schedule_campaign,
):
    state = _build_initial_state(
        _row(meta=_enabled_meta(batch_size=2)),
        pdd_ids=["p1", "p2", "p3"],
        mapping_ids=["m1", "m2", "m3"],
    )
    row = _row(meta={**_enabled_meta(batch_size=2), META_STATE_KEY: state}, campaign_run_id="camp_1")
    mock_get.return_value = row

    handled = maybe_handle_campaign_finished(
        row,
        run_id="camp_1",
        success=True,
        result={},
        error="",
    )

    assert handled is True
    mock_schedule_campaign.assert_called_once()
    assert mock_schedule_campaign.call_args.kwargs["activity_index"] == 1


@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator._enqueue_traffic_for_chunk")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.get_integrated_pipeline")
@patch(
    "pdd_agent.api.services.pipeline_service._campaign_run_already_handled",
    return_value=False,
)
@patch(
    "pdd_agent.api.services.pipeline_service._pipeline_activity_ids",
    return_value=["20981"],
)
@patch(
    "pdd_agent.api.services.pipeline_service._campaign_activity_index",
    return_value=0,
)
@patch(
    "pdd_agent.api.services.pipeline_service._summarize_run_message",
    return_value="ok",
)
def test_campaign_finished_enqueues_traffic_after_last_activity(
    mock_summary,
    mock_activity_index,
    mock_activity_ids,
    mock_already_handled,
    mock_get,
    mock_update,
    mock_enqueue_traffic,
):
    state = _build_initial_state(
        _row(meta=_enabled_meta(batch_size=2)),
        pdd_ids=["p1", "p2"],
        mapping_ids=["m1", "m2"],
    )
    state["activity_index"] = 0
    row = _row(meta={**_enabled_meta(batch_size=2), META_STATE_KEY: state}, campaign_run_id="camp_1")
    mock_get.return_value = row

    handled = maybe_handle_campaign_finished(
        row,
        run_id="camp_1",
        success=True,
        result={},
        error="",
    )

    assert handled is True
    mock_enqueue_traffic.assert_called_once()


@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator._start_next_chunk_activity")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.get_integrated_pipeline")
@patch(
    "pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge.maybe_record_traffic_finished",
)
@patch(
    "pdd_agent.api.services.pipeline_service._summarize_run_message",
    return_value="traffic ok",
)
def test_traffic_finished_starts_next_chunk(
    mock_summary,
    mock_record_traffic,
    mock_get,
    mock_update,
    mock_start_next_chunk,
):
    state = _build_initial_state(
        _row(meta=_enabled_meta(batch_size=2)),
        pdd_ids=["p1", "p2", "p3", "p4"],
        mapping_ids=["m1", "m2", "m3", "m4"],
    )
    state["phase"] = PHASE_TRAFFIC
    state["chunk_index"] = 0
    row = _row(meta={**_enabled_meta(batch_size=2), META_STATE_KEY: state}, traffic_run_id="traffic_1")
    mock_get.return_value = row
    mock_start_next_chunk.return_value = True

    handled = maybe_handle_traffic_finished(
        row,
        run_id="traffic_1",
        success=True,
        error="",
    )

    assert handled is True
    mock_start_next_chunk.assert_called_once()


@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator._complete_pipeline")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_activity_traffic_batch.orchestrator.get_integrated_pipeline")
@patch(
    "pdd_agent.api.services.pipeline_per_batch_lt_aggregate.bridge.maybe_record_traffic_finished",
)
@patch(
    "pdd_agent.api.services.pipeline_service._summarize_run_message",
    return_value="traffic ok",
)
@patch(
    "pdd_agent.api.services.pipeline_mq_auto_phase2.maybe_complete_mq_phase2_on_traffic_finished",
)
def test_traffic_finished_completes_on_last_chunk(
    mock_mq_phase2,
    mock_summary,
    mock_record_traffic,
    mock_get,
    mock_update,
    mock_complete,
):
    state = _build_initial_state(
        _row(meta=_enabled_meta(batch_size=2)),
        pdd_ids=["p1", "p2"],
        mapping_ids=["m1", "m2"],
    )
    state["phase"] = PHASE_TRAFFIC
    state["chunk_index"] = 1
    row = _row(meta={**_enabled_meta(batch_size=2), META_STATE_KEY: state}, traffic_run_id="traffic_1")
    mock_get.return_value = row

    handled = maybe_handle_traffic_finished(
        row,
        run_id="traffic_1",
        success=True,
        error="",
    )

    assert handled is True
    mock_complete.assert_called_once()

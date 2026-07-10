"""分批「限时→推广→活动」链路单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator import (
    handle_limited_time_finished,
    handle_traffic_finished,
    is_per_batch_lt_traffic_activity_enabled,
    per_batch_lt_traffic_activity_meta_patch,
    should_absorb_task_failure,
)


def _row(*, meta: dict | None = None, **kwargs):
    base_meta = {
        "listing_per_batch_lt_traffic_activity_enabled": True,
        "listing_per_batch_limited_time_enabled": True,
        "auto_limited_time_setup": True,
        "activity_ids": ["20981", "21365"],
        "listing_throttle": {
            "enabled": True,
            "total_batches": 3,
            "batch_index": 0,
            "interval_minutes": 15,
            "batches": [
                ["A/第一套/A1"],
                ["B/第一套/B1"],
                ["C/第一套/C1"],
            ],
            "listing_payload_base": {"category_keyword": "玩偶"},
            "accumulated_pdd_ids": ["111"],
            "accumulated_mapping_ids": ["map_1"],
        },
        "listing_per_batch_limited_time": {
            "enabled": True,
            "last_batch_index": 0,
            "awaiting_final_activity": False,
            "pending": {"next_batch_index": 1, "interval_minutes": 15},
        },
        "limited_time_run_id": "lt_run_1",
    }
    if meta:
        base_meta.update(meta)
    defaults = {
        "pipeline_id": "pipe_1",
        "account_id": "store_A",
        "activity_id": "20981",
        "auto_promotion": True,
        "meta": base_meta,
        "pdd_product_ids": ["111"],
        "mapping_ids": ["map_1"],
        "traffic_run_id": "",
        "campaign_run_id": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_meta_patch_enabled():
    assert per_batch_lt_traffic_activity_meta_patch(enabled=False) == {}
    assert per_batch_lt_traffic_activity_meta_patch(enabled=True) == {
        "listing_per_batch_lt_traffic_activity_enabled": True,
    }


def test_is_enabled_requires_throttle_and_per_batch_lt():
    row = _row()
    assert is_per_batch_lt_traffic_activity_enabled(row) is True
    row2 = _row(meta={"listing_per_batch_lt_traffic_activity_enabled": False})
    assert is_per_batch_lt_traffic_activity_enabled(row2) is False


@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.record_limited_time_batch")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator._resolve_lt_success_products")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator._enqueue_traffic")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.get_integrated_pipeline")
def test_lt_success_with_products_enqueues_traffic(
    mock_get,
    mock_update,
    mock_enqueue_traffic,
    mock_resolve_lt,
    mock_record_lt,
):
    mock_get.side_effect = lambda pid: _row()
    mock_resolve_lt.return_value = (["111"], ["map_1"])
    mock_enqueue_traffic.return_value = "traffic_run_1"

    handled = handle_limited_time_finished(
        _row(),
        run_id="lt_run_1",
        success=True,
        result={"results": []},
        error="",
    )

    assert handled is True
    mock_enqueue_traffic.assert_called_once()
    mock_record_lt.assert_called_once()


@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.record_limited_time_batch")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator._resolve_lt_success_products")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator._schedule_next_listing_batch")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.record_promotion_batch")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.update_integrated_pipeline")
def test_lt_success_without_products_skips_traffic_and_schedules_next_batch(
    mock_update,
    mock_record_promo,
    mock_schedule_next,
    mock_resolve_lt,
    mock_record_lt,
):
    mock_resolve_lt.return_value = ([], [])
    mock_schedule_next.return_value = True

    handled = handle_limited_time_finished(
        _row(),
        run_id="lt_run_1",
        success=True,
        result={},
        error="",
    )

    assert handled is True
    mock_record_promo.assert_called_once()
    mock_schedule_next.assert_called_once()


@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.record_limited_time_batch")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator._start_final_activities")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.record_promotion_batch")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.get_integrated_pipeline")
def test_final_batch_lt_failed_skips_traffic_starts_activity(
    mock_get,
    mock_update,
    mock_record_promo,
    mock_start_activity,
    mock_record_lt,
):
    meta = {
        "listing_per_batch_limited_time": {
            "enabled": True,
            "last_batch_index": 2,
            "awaiting_final_activity": True,
            "pending": None,
        },
        "listing_throttle": {
            "enabled": True,
            "total_batches": 3,
            "batch_index": 2,
            "interval_minutes": 15,
            "batches": [["A/1/A1"], ["B/1/B1"], ["C/1/C1"]],
            "listing_payload_base": {},
            "accumulated_pdd_ids": ["111", "222", "333"],
            "accumulated_mapping_ids": ["m1", "m2", "m3"],
            "completed": True,
        },
    }
    row = _row(meta=meta)
    mock_get.side_effect = lambda pid: row
    mock_start_activity.return_value = True

    handled = handle_limited_time_finished(
        row,
        run_id="lt_run_1",
        success=False,
        result={},
        error="限时失败",
    )

    assert handled is True
    mock_record_promo.assert_called_once()
    mock_start_activity.assert_called_once()


@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.record_promotion_batch")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator._schedule_next_listing_batch")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_traffic_activity.orchestrator.get_integrated_pipeline")
def test_traffic_failure_continues_next_batch(
    mock_get,
    mock_update,
    mock_schedule_next,
    mock_record_promo,
):
    meta = {
        "listing_per_batch_lt_traffic_activity": {
            "enabled": True,
            "phase": "traffic",
            "batch_index": 0,
            "is_final_batch": False,
            "lt_success_pdd_ids": ["111"],
            "pending_listing": {"next_batch_index": 1, "interval_minutes": 15},
        },
        "limited_time_run_id": "lt_run_1",
    }
    row = _row(meta=meta, traffic_run_id="traffic_run_1")
    mock_get.side_effect = lambda pid: row
    mock_schedule_next.return_value = True

    handled = handle_traffic_finished(
        row,
        run_id="traffic_run_1",
        success=False,
        error="推广失败",
    )

    assert handled is True
    mock_record_promo.assert_called_once()
    mock_schedule_next.assert_called_once()


def test_should_absorb_traffic_failure():
    meta = {
        "listing_per_batch_lt_traffic_activity": {
            "enabled": True,
            "phase": "traffic",
        },
    }
    row = _row(meta=meta, traffic_run_id="traffic_run_1")
    assert should_absorb_task_failure(row, agent="traffic", run_id="traffic_run_1", success=False) is True
    assert should_absorb_task_failure(row, agent="traffic", run_id="traffic_run_1", success=True) is False

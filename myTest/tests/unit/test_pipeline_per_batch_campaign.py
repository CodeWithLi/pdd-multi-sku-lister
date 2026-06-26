"""分批上架 — 每批完成后跑活动 / 推广。"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_per_batch_campaign import (
    is_per_batch_campaign_enabled,
    maybe_continue_after_per_batch_campaign,
    maybe_continue_after_per_batch_traffic,
    maybe_run_per_batch_campaign_after_listing,
    maybe_start_per_batch_campaign_after_limited_time,
    per_batch_campaign_meta_patch,
)


def _row(
    *,
    pipeline_id: str = "pipe_1",
    account_id: str = "store_A",
    meta: dict | None = None,
    auto_promotion: bool = True,
    campaign_run_id: str = "",
    traffic_run_id: str = "",
    activity_id: str = "20981",
):
    base_meta = {
        "activity_ids": ["20981", "20982"],
        "auto_limited_time_setup": True,
        "listing_per_batch_campaign_enabled": True,
        "listing_throttle": {
            "enabled": True,
            "batch_set_count": 1,
            "interval_minutes": 15,
            "total_batches": 3,
            "batch_index": 0,
            "batches": [
                ["BD713/第一套/BD713A"],
                ["BD720/第一套图/BD720A"],
                ["BD800/第二套/BD800A"],
            ],
            "listing_payload_base": {"category_keyword": "玩偶"},
            "accumulated_pdd_ids": [],
            "accumulated_mapping_ids": [],
        },
    }
    merged = {**base_meta, **(meta or {})}
    return SimpleNamespace(
        pipeline_id=pipeline_id,
        account_id=account_id,
        activity_id=activity_id,
        meta=merged,
        auto_promotion=auto_promotion,
        campaign_run_id=campaign_run_id,
        traffic_run_id=traffic_run_id,
        pdd_product_ids=["111"],
        mapping_ids=["map_1"],
    )


def test_per_batch_campaign_meta_patch():
    assert per_batch_campaign_meta_patch(enabled=False) == {}
    assert per_batch_campaign_meta_patch(enabled=True) == {
        "listing_per_batch_campaign_enabled": True,
    }


def test_is_per_batch_campaign_enabled():
    assert is_per_batch_campaign_enabled(_row()) is True


@patch("pdd_agent.api.services.pipeline_per_batch_campaign.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_campaign.enqueue_task")
@patch("pdd_agent.api.services.pipeline_per_batch_campaign.create_campaign_run")
def test_maybe_run_campaign_after_listing(mock_create_run, mock_enqueue, mock_update):
    mock_create_run.return_value = "camp_1"
    row = _row(meta={"listing_per_batch_limited_time_enabled": False})

    handled = maybe_run_per_batch_campaign_after_listing(
        row,
        pdd_ids=["111"],
        mapping_ids=["map_1"],
    )

    assert handled is True
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["payload"]["campaign_type"] == "marketing_activity_register"
    assert mock_enqueue.call_args.kwargs["payload"]["pdd_product_ids"] == ["111"]


@patch("pdd_agent.api.services.pipeline_per_batch_campaign._start_batch_campaign_chain")
def test_maybe_run_campaign_skipped_when_per_batch_lt_enabled(mock_start):
    row = _row(meta={"listing_per_batch_limited_time_enabled": True})
    assert (
        maybe_run_per_batch_campaign_after_listing(
            row,
            pdd_ids=["111"],
            mapping_ids=["map_1"],
        )
        is False
    )
    mock_start.assert_not_called()


@patch("pdd_agent.api.services.pipeline_per_batch_campaign._start_batch_campaign_chain")
def test_maybe_start_campaign_after_limited_time(mock_start):
    row = _row(
        meta={
            "listing_per_batch_limited_time_enabled": True,
            "limited_time_run_id": "lt_1",
            "listing_per_batch_limited_time": {
                "enabled": True,
                "pending": {
                    "next_batch_index": 1,
                    "next_batch_scheduled_at": (datetime.now() + timedelta(minutes=15)).isoformat(
                        timespec="seconds"
                    ),
                },
            },
        }
    )
    mock_start.return_value = True

    assert maybe_start_per_batch_campaign_after_limited_time(row, run_id="lt_1", success=True) is True
    mock_start.assert_called_once()


@patch("pdd_agent.api.services.pipeline_per_batch_campaign._enqueue_traffic_for_batch")
@patch("pdd_agent.api.services.pipeline_per_batch_campaign._pipeline_activity_ids")
def test_maybe_continue_campaign_starts_traffic_after_last_activity(
    mock_activity_ids,
    mock_enqueue_traffic,
):
    mock_activity_ids.return_value = ["20981"]
    meta = {
        "listing_per_batch_campaign": {
            "enabled": True,
            "phase": "campaign",
            "activity_index": 0,
            "batch_pdd_ids": ["111"],
            "batch_mapping_ids": ["map_1"],
            "is_final_batch": False,
            "pending_listing": {
                "next_batch_index": 1,
                "next_batch_scheduled_at": (datetime.now() + timedelta(minutes=15)).isoformat(
                    timespec="seconds"
                ),
            },
        }
    }
    row = _row(meta=meta, campaign_run_id="camp_1")
    mock_enqueue_traffic.return_value = "traffic_1"

    handled = maybe_continue_after_per_batch_campaign(
        row,
        run_id="camp_1",
        success=True,
        result={},
    )

    assert handled is True
    mock_enqueue_traffic.assert_called_once()


@patch("pdd_agent.api.services.pipeline_per_batch_campaign._complete_per_batch_pipeline")
def test_maybe_continue_traffic_completes_final_batch(mock_complete):
    meta = {
        "listing_per_batch_campaign": {
            "enabled": True,
            "phase": "traffic",
            "is_final_batch": True,
        }
    }
    row = _row(meta=meta, traffic_run_id="traffic_1")

    handled = maybe_continue_after_per_batch_traffic(row, run_id="traffic_1", success=True)

    assert handled is True
    mock_complete.assert_called_once()

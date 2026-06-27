"""分批上架 — 每批完成后跑限时限量购。"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_per_batch_limited_time import (
    is_per_batch_limited_time_enabled,
    maybe_continue_after_per_batch_limited_time,
    maybe_run_per_batch_limited_time_after_listing,
    per_batch_limited_time_meta_patch,
    prepare_pipeline_row_for_post_listing_steps,
)


def _row(
    *,
    pipeline_id: str = "pipe_1",
    account_id: str = "store_A",
    meta: dict | None = None,
    pdd_product_ids: list[str] | None = None,
    mapping_ids: list[str] | None = None,
):
    return SimpleNamespace(
        pipeline_id=pipeline_id,
        account_id=account_id,
        meta=meta or {},
        pdd_product_ids=pdd_product_ids or [],
        mapping_ids=mapping_ids or [],
    )


def _throttle_meta(*, batch_index: int = 0, total_batches: int = 3) -> dict:
    return {
        "listing_throttle": {
            "enabled": True,
            "batch_set_count": 1,
            "interval_minutes": 15,
            "total_batches": total_batches,
            "batch_index": batch_index,
            "batches": [
                ["BD713/第一套/BD713A"],
                ["BD720/第一套图/BD720A"],
                ["BD800/第二套/BD800A"],
            ],
            "listing_payload_base": {"category_keyword": "玩偶"},
            "accumulated_pdd_ids": [],
            "accumulated_mapping_ids": [],
        },
        "listing_per_batch_limited_time_enabled": True,
        "auto_limited_time_setup": True,
    }


def test_per_batch_limited_time_meta_patch():
    assert per_batch_limited_time_meta_patch(enabled=False) == {}
    assert per_batch_limited_time_meta_patch(enabled=True) == {
        "listing_per_batch_limited_time_enabled": True,
    }


def test_is_per_batch_limited_time_enabled():
    row = _row(meta={"listing_per_batch_limited_time_enabled": True})
    assert is_per_batch_limited_time_enabled(row) is True


@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.enqueue_task")
@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.create_campaign_run")
def test_maybe_run_enqueues_limited_time_for_current_batch_when_more_batches(
    mock_create_run,
    mock_enqueue,
    mock_update,
):
    mock_create_run.return_value = "lt_run_1"
    row = _row(meta=_throttle_meta(batch_index=0, total_batches=3))

    handled = maybe_run_per_batch_limited_time_after_listing(
        row,
        pdd_ids=["111"],
        mapping_ids=["map_1"],
        listing_meta={"listing_summary": "ok"},
    )

    assert handled is True
    mock_enqueue.assert_called_once()
    payload = mock_enqueue.call_args.kwargs["payload"]
    assert payload["pdd_product_ids"] == ["111"]
    assert payload["published_mapping_ids"] == ["map_1"]
    meta_patch = mock_update.call_args.kwargs["meta_patch"]
    assert meta_patch["listing_per_batch_limited_time"]["pending"]["next_batch_index"] == 1
    assert meta_patch["listing_throttle"]["accumulated_pdd_ids"] == ["111"]


@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.enqueue_task")
@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.create_campaign_run")
def test_maybe_run_marks_final_batch(mock_create_run, mock_enqueue, mock_update):
    mock_create_run.return_value = "lt_run_final"
    row = _row(meta=_throttle_meta(batch_index=2, total_batches=3))

    handled = maybe_run_per_batch_limited_time_after_listing(
        row,
        pdd_ids=["333"],
        mapping_ids=["map_3"],
    )

    assert handled is True
    meta_patch = mock_update.call_args.kwargs["meta_patch"]
    assert meta_patch["listing_per_batch_limited_time"]["awaiting_final_activity"] is True
    assert "pending" not in meta_patch["listing_per_batch_limited_time"]
    assert meta_patch["listing_throttle"]["completed"] is True


def test_maybe_run_returns_false_when_disabled():
    row = _row(meta=_throttle_meta())
    row.meta.pop("listing_per_batch_limited_time_enabled")
    assert (
        maybe_run_per_batch_limited_time_after_listing(
            row,
            pdd_ids=["111"],
            mapping_ids=["map_1"],
        )
        is False
    )


@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.enqueue_listing_batch_for_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.update_integrated_pipeline")
def test_maybe_continue_schedules_next_listing_batch(
    mock_update,
    mock_get,
    mock_enqueue_listing,
):
    meta = _throttle_meta(batch_index=0, total_batches=3)
    meta["limited_time_run_id"] = "lt_run_1"
    meta["listing_per_batch_limited_time"] = {
        "enabled": True,
        "last_batch_index": 0,
        "awaiting_final_activity": False,
        "pending": {
            "next_batch_index": 1,
            "next_batch_scheduled_at": (datetime.now() + timedelta(minutes=10)).isoformat(
                timespec="seconds"
            ),
        },
    }
    row = _row(meta=meta)
    mock_get.return_value = row

    handled = maybe_continue_after_per_batch_limited_time(
        row,
        run_id="lt_run_1",
        success=True,
    )

    assert handled is True
    mock_enqueue_listing.assert_called_once()
    assert mock_enqueue_listing.call_args.kwargs["batch_codes"] == ["BD720/第一套图/BD720A"]


@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.enqueue_listing_batch_for_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.update_integrated_pipeline")
def test_maybe_continue_after_lt_failure_still_schedules_next_listing_batch(
    mock_update,
    mock_get,
    mock_enqueue_listing,
):
    meta = _throttle_meta(batch_index=0, total_batches=3)
    meta["limited_time_run_id"] = "lt_run_1"
    meta["listing_per_batch_limited_time"] = {
        "enabled": True,
        "last_batch_index": 0,
        "awaiting_final_activity": False,
        "pending": {
            "next_batch_index": 1,
            "next_batch_scheduled_at": (datetime.now() + timedelta(minutes=10)).isoformat(
                timespec="seconds"
            ),
        },
    }
    row = _row(meta=meta)
    mock_get.return_value = row

    handled = maybe_continue_after_per_batch_limited_time(
        row,
        run_id="lt_run_1",
        success=False,
        error="限时限量购设置失败",
    )

    assert handled is True
    mock_enqueue_listing.assert_called_once()
    assert any(
        call.kwargs.get("status") == "running" for call in mock_update.call_args_list
    )


def test_maybe_continue_returns_false_for_final_batch():
    meta = _throttle_meta(batch_index=2, total_batches=3)
    meta["limited_time_run_id"] = "lt_run_final"
    meta["listing_per_batch_limited_time"] = {
        "enabled": True,
        "awaiting_final_activity": True,
    }
    row = _row(meta=meta)

    assert (
        maybe_continue_after_per_batch_limited_time(
            row,
            run_id="lt_run_final",
            success=True,
        )
        is False
    )


@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_per_batch_limited_time.update_integrated_pipeline")
def test_prepare_pipeline_row_for_post_listing_steps(mock_update, mock_get):
    meta = _throttle_meta(batch_index=2, total_batches=3)
    meta["listing_throttle"]["accumulated_pdd_ids"] = ["111", "222", "333"]
    meta["listing_throttle"]["accumulated_mapping_ids"] = ["m1", "m2", "m3"]
    meta["listing_per_batch_limited_time"] = {
        "enabled": True,
        "awaiting_final_activity": True,
    }
    row = _row(meta=meta)
    refreshed = _row(
        meta=meta,
        pdd_product_ids=["111", "222", "333"],
        mapping_ids=["m1", "m2", "m3"],
    )
    mock_get.return_value = refreshed

    result = prepare_pipeline_row_for_post_listing_steps(row)

    mock_update.assert_called_once_with(
        "pipe_1",
        pdd_product_ids=["111", "222", "333"],
        mapping_ids=["m1", "m2", "m3"],
    )
    assert result.pdd_product_ids == ["111", "222", "333"]

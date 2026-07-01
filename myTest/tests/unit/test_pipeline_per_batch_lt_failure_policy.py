"""分批限时限量购失败策略测试。"""

from __future__ import annotations

from types import SimpleNamespace

from pdd_agent.api.services.pipeline_per_batch_lt_failure_policy import (
    has_pending_throttled_listing_batches,
    should_absorb_per_batch_limited_time_failure,
    should_block_sequential_store_advance,
)


def _row(*, pipeline_id: str = "pipe_1", meta: dict | None = None, current_step: str = ""):
    return SimpleNamespace(
        pipeline_id=pipeline_id,
        meta=meta or {},
        current_step=current_step,
    )


def _per_batch_meta(*, batch_index: int = 0, total_batches: int = 14) -> dict:
    return {
        "listing_per_batch_limited_time_enabled": True,
        "auto_limited_time_setup": True,
        "limited_time_run_id": "lt_run_1",
        "listing_throttle": {
            "enabled": True,
            "batch_index": batch_index,
            "total_batches": total_batches,
            "batches": [["a"]] * total_batches,
            "interval_minutes": 3,
        },
        "per_batch_limited_time": {
            "enabled": True,
            "pending": {"next_batch_index": batch_index + 1, "interval_minutes": 3},
        },
    }


def test_absorb_mid_batch_limited_time_failure_without_continue_flag():
    row = _row(meta=_per_batch_meta(batch_index=2, total_batches=14))
    assert should_absorb_per_batch_limited_time_failure(row, run_id="lt_run_1") is True


def test_no_absorb_final_batch_without_continue_flag():
    row = _row(
        meta={
            **_per_batch_meta(batch_index=13, total_batches=14),
            "per_batch_limited_time": {"enabled": True, "pending": None},
            "listing_throttle": {
                "enabled": True,
                "batch_index": 13,
                "total_batches": 14,
                "batches": [["a"]] * 14,
                "completed": True,
            },
        }
    )
    assert should_absorb_per_batch_limited_time_failure(row, run_id="lt_run_1") is False


def test_absorb_final_batch_when_continue_flag_enabled():
    row = _row(
        meta={
            **_per_batch_meta(batch_index=13, total_batches=14),
            "continue_after_limited_time_failure": True,
            "per_batch_limited_time": {"enabled": True, "pending": None},
            "listing_throttle": {
                "enabled": True,
                "batch_index": 13,
                "total_batches": 14,
                "batches": [["a"]] * 14,
                "completed": True,
            },
        }
    )
    assert should_absorb_per_batch_limited_time_failure(row, run_id="lt_run_1") is True


def test_has_pending_batches_from_waiting_step():
    row = _row(
        meta=_per_batch_meta(batch_index=2, total_batches=14),
        current_step="waiting_listing_batch_4",
    )
    assert has_pending_throttled_listing_batches(row) is True


def test_block_sequential_store_advance_while_batches_pending():
    row = _row(meta=_per_batch_meta(batch_index=2, total_batches=14))
    assert should_block_sequential_store_advance(row) is True


def test_allow_sequential_store_advance_after_all_batches_done():
    row = _row(
        meta={
            "listing_per_batch_limited_time_enabled": True,
            "auto_limited_time_setup": True,
            "listing_throttle": {
                "enabled": True,
                "batch_index": 13,
                "total_batches": 14,
                "batches": [["a"]] * 14,
                "completed": True,
            },
            "per_batch_limited_time": {"enabled": True, "pending": None},
        }
    )
    assert should_block_sequential_store_advance(row) is False

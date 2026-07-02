"""分批每批限时 + 仅限时成功报活动 — 中间批失败策略。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_lt_middle_batch_success_only_policy import (
    POLICY_META_FLAG,
    is_policy_enabled,
    maybe_handle_middle_batch_before_success_only_finish,
    should_skip_success_only_limited_time_finish,
)


def _row(*, meta: dict | None = None):
    return SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="store_A",
        current_step="limited_time_queued",
        meta=meta or {},
    )


def _throttle_meta(*, batch_index: int = 2, total_batches: int = 16) -> dict:
    batches = [[f"batch_{i}"] for i in range(total_batches)]
    return {
        "activity_limited_time_success_only": True,
        "listing_per_batch_limited_time_enabled": True,
        "auto_limited_time_setup": True,
        "limited_time_run_id": "lt_run_3",
        "listing_throttle": {
            "enabled": True,
            "batch_set_count": 10,
            "interval_minutes": 3,
            "total_batches": total_batches,
            "batch_index": batch_index,
            "batches": batches,
            "listing_payload_base": {"category_keyword": "玩偶"},
        },
        "listing_per_batch_limited_time": {
            "enabled": True,
            "last_batch_index": batch_index,
            "awaiting_final_activity": False,
            "pending": {
                "next_batch_index": batch_index + 1,
                "interval_minutes": 3,
            },
        },
    }


def test_should_skip_on_middle_batch_with_success_only():
    row = _row(meta=_throttle_meta(batch_index=2, total_batches=16))
    assert should_skip_success_only_limited_time_finish(row) is True


def test_should_not_skip_on_final_batch():
    meta = _throttle_meta(batch_index=15, total_batches=16)
    meta["listing_per_batch_limited_time"] = {
        "enabled": True,
        "awaiting_final_activity": True,
    }
    meta["listing_per_batch_limited_time"].pop("pending", None)
    row = _row(meta=meta)
    assert should_skip_success_only_limited_time_finish(row) is False


def test_policy_can_be_disabled_via_meta():
    meta = _throttle_meta()
    meta[POLICY_META_FLAG] = False
    row = _row(meta=meta)
    assert is_policy_enabled(row) is False
    assert should_skip_success_only_limited_time_finish(row) is False


@patch(
    "pdd_agent.api.services.pipeline_lt_middle_batch_success_only_policy._continue_next_listing_batch_relaxed"
)
@patch(
    "pdd_agent.api.services.pipeline_per_batch_limited_time.maybe_continue_after_per_batch_limited_time"
)
def test_handle_delegates_to_maybe_continue_first(mock_maybe_continue, mock_relaxed):
    mock_maybe_continue.return_value = True
    row = _row(meta=_throttle_meta())

    handled = maybe_handle_middle_batch_before_success_only_finish(
        row,
        run_id="lt_run_3",
        success=False,
        error="未能点击创建",
    )

    assert handled is True
    mock_maybe_continue.assert_called_once()
    mock_relaxed.assert_not_called()


@patch(
    "pdd_agent.api.services.pipeline_lt_middle_batch_success_only_policy._continue_next_listing_batch_relaxed"
)
@patch(
    "pdd_agent.api.services.pipeline_per_batch_limited_time.maybe_continue_after_per_batch_limited_time"
)
def test_handle_falls_back_to_relaxed_continue(mock_maybe_continue, mock_relaxed):
    mock_maybe_continue.return_value = False
    mock_relaxed.return_value = True
    row = _row(meta=_throttle_meta())

    handled = maybe_handle_middle_batch_before_success_only_finish(
        row,
        run_id="lt_run_3",
        success=False,
        error="未能点击创建",
    )

    assert handled is True
    mock_relaxed.assert_called_once()


@patch(
    "pdd_agent.api.services.pipeline_lt_middle_batch_success_only_policy.update_integrated_pipeline"
)
@patch(
    "pdd_agent.api.services.pipeline_lt_middle_batch_success_only_policy.get_integrated_pipeline"
)
@patch(
    "pdd_agent.api.services.pipeline_per_batch_limited_time.maybe_continue_after_per_batch_limited_time"
)
def test_handle_syncs_stale_limited_time_run_id_before_continue(
    mock_maybe_continue,
    mock_get,
    mock_update,
):
    meta = _throttle_meta()
    meta["limited_time_run_id"] = "lt_run_stale"
    row = _row(meta=meta)
    refreshed = _row(meta={**meta, "limited_time_run_id": "lt_run_new"})
    mock_get.return_value = refreshed
    mock_maybe_continue.return_value = True

    maybe_handle_middle_batch_before_success_only_finish(
        row,
        run_id="lt_run_new",
        success=False,
        error="fail",
    )

    assert mock_update.called
    assert mock_update.call_args.kwargs["meta_patch"]["limited_time_run_id"] == "lt_run_new"

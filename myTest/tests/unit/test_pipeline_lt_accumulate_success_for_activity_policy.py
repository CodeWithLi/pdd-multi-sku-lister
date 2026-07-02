"""跨批累计限时成功商品 — 活动报名策略。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy import (
    ACCUMULATED_PDD_IDS_KEY,
    POLICY_META_FLAG,
    accumulate_per_batch_limited_time_success,
    is_policy_enabled,
    maybe_finalize_limited_time_success_only_with_accumulation,
)


def _row(*, meta: dict | None = None):
    return SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="store_A",
        current_step="waiting_limited_time_per_batch",
        pdd_product_ids=["999"],
        mapping_ids=[],
        meta=meta or {},
    )


def _throttle_meta(*, batch_index: int = 15, total_batches: int = 16, final_batch: bool = True) -> dict:
    batches = [[f"batch_{i}"] for i in range(total_batches)]
    lt_state: dict = {
        "enabled": True,
        "last_batch_index": batch_index,
    }
    if final_batch:
        lt_state["awaiting_final_activity"] = True
    else:
        lt_state["awaiting_final_activity"] = False
        lt_state["pending"] = {"next_batch_index": batch_index + 1, "interval_minutes": 3}
    return {
        "activity_limited_time_success_only": True,
        "listing_per_batch_limited_time_enabled": True,
        "auto_limited_time_setup": True,
        ACCUMULATED_PDD_IDS_KEY: ["111", "222"],
        "listing_throttle": {
            "enabled": True,
            "total_batches": total_batches,
            "batch_index": batch_index,
            "batches": batches,
            "interval_minutes": 3,
            "listing_payload_base": {},
        },
        "listing_per_batch_limited_time": lt_state,
    }


def test_policy_can_be_disabled_via_meta():
    meta = _throttle_meta()
    meta[POLICY_META_FLAG] = False
    assert is_policy_enabled(_row(meta=meta)) is False


@patch("pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy.get_integrated_pipeline")
@patch(
    "pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy._extract_current_batch_success"
)
def test_accumulate_merges_current_batch_into_meta(mock_extract, mock_get, mock_update):
    from pdd_agent.api.services.pipeline_activity_limited_time_success import LimitedTimeSuccessProducts

    mock_extract.return_value = LimitedTimeSuccessProducts(
        pdd_product_ids=["333"],
        mapping_ids=["m3"],
        source="limited_time_success",
        detail="ok",
    )
    row = _row(meta=_throttle_meta(batch_index=2, final_batch=False))
    refreshed = _row(meta={**row.meta, ACCUMULATED_PDD_IDS_KEY: ["111", "222", "333"]})
    mock_get.return_value = refreshed

    result = accumulate_per_batch_limited_time_success(
        row,
        run_id="lt_3",
        result={"results": []},
    )

    assert mock_update.called
    patch_meta = mock_update.call_args.kwargs["meta_patch"]
    assert patch_meta[ACCUMULATED_PDD_IDS_KEY] == ["111", "222", "333"]
    assert result is refreshed


@patch("pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy.update_integrated_pipeline")
@patch(
    "pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy._build_merged_activity_products"
)
def test_finalize_schedules_activity_with_accumulated_only_on_final_batch_failure(
    mock_build,
    mock_update,
    mock_get,
):
    from pdd_agent.api.services.pipeline_activity_limited_time_success import LimitedTimeSuccessProducts

    mock_build.return_value = LimitedTimeSuccessProducts(
        pdd_product_ids=["111", "222"],
        mapping_ids=["m1", "m2"],
        source="accumulated_limited_time_success",
        detail="跨批累计限时成功 2 个商品（本批无成功，使用历史累计）",
    )
    row = _row(meta=_throttle_meta(batch_index=15, final_batch=True))
    mock_get.return_value = row
    schedule_fn = MagicMock()
    advance_fn = MagicMock()

    handled = maybe_finalize_limited_time_success_only_with_accumulation(
        row,
        run_id="lt_final",
        success=False,
        result={"errors": ["fail"]},
        error="未能点击创建",
        schedule_activity_fn=schedule_fn,
        advance_store_sequential_fn=advance_fn,
    )

    assert handled is True
    schedule_fn.assert_called_once()
    assert schedule_fn.call_args.kwargs["pdd_ids"] == ["111", "222"]
    advance_fn.assert_called_once()
    meta_patch = mock_update.call_args.kwargs["meta_patch"]
    assert meta_patch["limited_time_outcome"] == "partial_success"


@patch(
    "pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy._build_merged_activity_products"
)
def test_finalize_returns_false_when_no_accumulated_products(mock_build):
    from pdd_agent.api.services.pipeline_activity_limited_time_success import LimitedTimeSuccessProducts

    mock_build.return_value = LimitedTimeSuccessProducts(
        pdd_product_ids=[],
        mapping_ids=[],
        source="none",
        detail="",
    )
    row = _row(meta=_throttle_meta(batch_index=15, final_batch=True))

    handled = maybe_finalize_limited_time_success_only_with_accumulation(
        row,
        run_id="lt_final",
        success=False,
        result={},
        error="fail",
        schedule_activity_fn=MagicMock(),
        advance_store_sequential_fn=MagicMock(),
    )

    assert handled is False


@patch(
    "pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy._build_merged_activity_products"
)
def test_finalize_skips_middle_batch(mock_build):
    row = _row(meta=_throttle_meta(batch_index=2, final_batch=False))

    handled = maybe_finalize_limited_time_success_only_with_accumulation(
        row,
        run_id="lt_3",
        success=True,
        result={},
        error="",
        schedule_activity_fn=MagicMock(),
        advance_store_sequential_fn=MagicMock(),
    )

    assert handled is False
    mock_build.assert_not_called()

"""限时失败跳过活动仍推广 — 策略模块单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from pdd_agent.api.services.pipeline_lt_failure_promotion_policy import (
    CAMPAIGN_OUTCOME,
    META_FLAG,
    PRODUCT_SOURCE_LISTING,
    PRODUCT_SOURCE_LT,
    maybe_lt_failure_skip_activity_and_enqueue_promotion,
    resolve_traffic_product_ids_if_lt_skip,
)


def _row(**kwargs):
    defaults = {
        "pipeline_id": "pipe_1",
        "account_id": "store_A",
        "auto_promotion": True,
        "pdd_product_ids": ["111", "222"],
        "mapping_ids": ["m1", "m2"],
        "meta": {META_FLAG: True},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.is_final_limited_time_decision_row", return_value=True)
@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.get_lt_failure_promotion_product_source")
@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.resolve_listing_success_product_ids")
def test_skip_activity_enqueue_promotion_with_listing_success(
    mock_resolve,
    mock_get,
    mock_update,
    mock_source,
    _mock_final,
):
    mock_source.return_value = PRODUCT_SOURCE_LISTING
    mock_resolve.return_value = (["111"], ["m1"], "上架成功商品 1 个")
    row = _row()
    mock_get.return_value = row
    enqueue = Mock()

    handled = maybe_lt_failure_skip_activity_and_enqueue_promotion(
        row,
        run_id="lt_1",
        success=False,
        result={},
        error="活动价格不符合价格区间，不继续创建活动",
        enqueue_traffic_fn=enqueue,
    )

    assert handled is True
    enqueue.assert_called_once()
    meta_patch = mock_update.call_args.kwargs.get("meta_patch") or mock_update.call_args_list[0].kwargs.get("meta_patch")
    assert meta_patch["campaign_outcome"] == CAMPAIGN_OUTCOME


@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.is_final_limited_time_decision_row", return_value=True)
@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.get_lt_failure_promotion_product_source")
@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.resolve_listing_success_product_ids")
@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.update_integrated_pipeline")
def test_listing_success_empty_completes_without_promotion(
    mock_update,
    mock_resolve,
    mock_source,
    _mock_final,
):
    mock_source.return_value = PRODUCT_SOURCE_LISTING
    mock_resolve.return_value = ([], [], "上架成功商品 0 个")
    row = _row()

    handled = maybe_lt_failure_skip_activity_and_enqueue_promotion(
        row,
        run_id="lt_1",
        success=False,
        result={},
        error="活动价格不符合价格区间",
        enqueue_traffic_fn=Mock(),
    )

    assert handled is True
    assert mock_update.call_args.kwargs["status"] == "completed"
    assert mock_update.call_args.kwargs["current_step"] == "completed"


@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.is_final_limited_time_decision_row", return_value=True)
@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.get_lt_failure_promotion_product_source")
@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.resolve_limited_time_success_product_ids")
def test_limited_time_success_empty_falls_through(mock_resolve, mock_source, _mock_final):
    mock_source.return_value = PRODUCT_SOURCE_LT
    mock_resolve.return_value = ([], [], "无限时提交成功商品")
    row = _row()

    handled = maybe_lt_failure_skip_activity_and_enqueue_promotion(
        row,
        run_id="lt_1",
        success=False,
        result={},
        error="活动价格不符合价格区间",
        enqueue_traffic_fn=Mock(),
    )

    assert handled is False


@patch("pdd_agent.api.services.pipeline_lt_failure_promotion_policy.is_final_limited_time_decision_row")
def test_not_final_batch_does_not_trigger(mock_final):
    mock_final.return_value = False
    row = _row(meta={META_FLAG: True, "listing_per_batch_limited_time": {"enabled": True}})

    handled = maybe_lt_failure_skip_activity_and_enqueue_promotion(
        row,
        run_id="lt_1",
        success=False,
        result={},
        error="fail",
        enqueue_traffic_fn=Mock(),
    )

    assert handled is False


def test_resolve_traffic_product_ids_if_lt_skip():
    row = _row(
        meta={
            "campaign_outcome": CAMPAIGN_OUTCOME,
            "lt_failure_skip_activity_promotion_pdd_product_ids": ["111"],
            "lt_failure_skip_activity_promotion_mapping_ids": ["m1"],
        }
    )
    assert resolve_traffic_product_ids_if_lt_skip(row) == (["111"], ["m1"])

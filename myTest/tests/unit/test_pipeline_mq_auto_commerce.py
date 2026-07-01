"""MQ 自动链路 — 阶段一完成后释放店铺占用。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_mq_auto_commerce import (
    META_STORE_RELEASED_KEY,
    is_mq_commerce_store_released,
    release_mq_store_after_phase1,
    should_mq_pipeline_skip_commerce_sync,
)


def test_is_mq_commerce_store_released():
    row = SimpleNamespace(meta={META_STORE_RELEASED_KEY: True})
    assert is_mq_commerce_store_released(row)


def test_should_skip_commerce_sync_when_released():
    row = SimpleNamespace(
        pipeline_id="p1",
        meta={"mq_auto_deferred_phase2": True, META_STORE_RELEASED_KEY: True},
    )
    assert should_mq_pipeline_skip_commerce_sync(row)


@patch("pdd_agent.api.services.pipeline_mq_auto_commerce.update_integrated_pipeline")
@patch("pdd_agent.api.services.commerce_dispatch.try_dispatch_pending_for_account")
@patch("pdd_agent.api.services.commerce_dispatch._force_clear_account_lifecycle")
def test_release_mq_store_after_phase1(mock_clear, mock_dispatch, mock_update):
    mock_clear.return_value = True
    mock_dispatch.return_value = {"dispatched": True, "pipeline_id": "next_p"}
    row = SimpleNamespace(
        pipeline_id="p1",
        account_id="shop_a",
        meta={"mq_auto_deferred_phase2": True},
    )
    result = release_mq_store_after_phase1(row)
    assert result["released"] is True
    assert result["lifecycle_cleared"] is True
    mock_clear.assert_called_once_with("shop_a", reason="mq_phase1_complete")
    mock_dispatch.assert_called_once_with("shop_a")
    mock_update.assert_called_once()
    assert mock_update.call_args.kwargs["meta_patch"][META_STORE_RELEASED_KEY] is True


@patch("pdd_agent.api.services.pipeline_mq_auto_commerce.update_integrated_pipeline")
@patch("pdd_agent.api.services.commerce_dispatch.try_dispatch_pending_for_account")
@patch("pdd_agent.api.services.commerce_dispatch._force_clear_account_lifecycle")
def test_release_mq_store_idempotent(mock_clear, mock_dispatch, mock_update):
    row = SimpleNamespace(
        pipeline_id="p1",
        account_id="shop_a",
        meta={"mq_auto_deferred_phase2": True, META_STORE_RELEASED_KEY: True},
    )
    result = release_mq_store_after_phase1(row)
    assert result["released"] is False
    assert result["reason"] == "already_released"
    mock_clear.assert_not_called()
    mock_dispatch.assert_not_called()
    mock_update.assert_not_called()

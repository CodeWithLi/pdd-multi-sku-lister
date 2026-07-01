"""MQ 阶段二 — 店铺空闲检测。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_mq_auto_commerce import (
    META_PHASE2_WAIT_REASON,
    assess_mq_phase2_account_idle,
    format_mq_phase2_wait_detail,
    record_mq_phase2_wait_for_account_idle,
)


@patch("pdd_agent.api.services.commerce_dispatch._list_non_terminal_pipeline_ids_for_account")
@patch("pdd_agent.api.services.commerce_dispatch.list_pending_intents")
@patch("pdd_agent.api.services.commerce_dispatch._get_account_lifecycle")
@patch("pdd_agent.db.repositories.count_account_queue_tasks")
@patch("pdd_agent.db.repositories.list_busy_account_ids")
def test_assess_ready_when_idle(
    mock_busy,
    mock_queued,
    mock_lc,
    mock_pending,
    mock_pipelines,
):
    mock_busy.return_value = set()
    mock_queued.return_value = 0
    mock_lc.return_value = None
    mock_pending.return_value = []
    mock_pipelines.return_value = []
    result = assess_mq_phase2_account_idle(account_id="shop_a", pipeline_id="p1")
    assert result["ready"] is True


@patch("pdd_agent.api.services.commerce_dispatch._list_non_terminal_pipeline_ids_for_account")
@patch("pdd_agent.api.services.commerce_dispatch.list_pending_intents")
@patch("pdd_agent.api.services.commerce_dispatch._get_account_lifecycle")
@patch("pdd_agent.db.repositories.count_account_queue_tasks")
@patch("pdd_agent.db.repositories.list_busy_account_ids")
def test_assess_not_ready_when_queue_pending(
    mock_busy,
    mock_queued,
    mock_lc,
    mock_pending,
    mock_pipelines,
):
    mock_busy.return_value = set()
    mock_queued.return_value = 2
    mock_lc.return_value = None
    mock_pending.return_value = []
    mock_pipelines.return_value = []
    result = assess_mq_phase2_account_idle(account_id="shop_a", pipeline_id="p1")
    assert result["ready"] is False
    assert result["reason"] == "queue_pending"


@patch("pdd_agent.db.repositories.get_integrated_pipeline")
@patch("pdd_agent.api.services.commerce_dispatch._list_non_terminal_pipeline_ids_for_account")
@patch("pdd_agent.api.services.commerce_dispatch.list_pending_intents")
@patch("pdd_agent.api.services.commerce_dispatch._get_account_lifecycle")
@patch("pdd_agent.db.repositories.count_account_queue_tasks")
@patch("pdd_agent.db.repositories.list_busy_account_ids")
def test_assess_ignores_peer_waiting_mq_phase2(
    mock_busy,
    mock_queued,
    mock_lc,
    mock_pending,
    mock_pipelines,
    mock_get,
):
    mock_busy.return_value = set()
    mock_queued.return_value = 0
    mock_lc.return_value = None
    mock_pending.return_value = []
    mock_pipelines.return_value = ["p1", "p2"]
    mock_get.return_value = SimpleNamespace(current_step="waiting_mq_phase2")
    result = assess_mq_phase2_account_idle(account_id="shop_a", pipeline_id="p1")
    assert result["ready"] is True


def test_format_mq_phase2_wait_detail():
    text = format_mq_phase2_wait_detail(
        {META_PHASE2_WAIT_REASON: "queue_pending", "mq_phase2_wait_detail": "queued_tasks=1"}
    )
    assert "等待店铺空闲" in text
    assert "排队任务" in text


@patch("pdd_agent.api.services.pipeline_mq_auto_commerce.update_integrated_pipeline")
def test_record_mq_phase2_wait(mock_update):
    row = SimpleNamespace(pipeline_id="p1", account_id="shop_a", meta={})
    record_mq_phase2_wait_for_account_idle(
        row,
        {"reason": "other_pipeline", "detail": "p2:listing_queued"},
    )
    mock_update.assert_called_once()

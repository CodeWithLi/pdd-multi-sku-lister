"""RabbitMQ 多店铺串行 + 阶段二延迟调度。"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.integrations.minio.auto_pipeline import (
    AutoPipelineConfig,
    _dedup_key,
    resolve_auto_pipeline_account_ids,
)
from pdd_agent.api.services.pipeline_mq_auto_phase2 import (
    STEP_WAITING,
    compute_mq_phase2_due_at,
    handle_mq_auto_limited_time_finished,
    is_mq_auto_deferred_phase2_row,
    start_mq_phase2,
    tick_mq_auto_phase2,
)


def test_auto_pipeline_account_ids_normalize():
    cfg = AutoPipelineConfig(account_id="shop_a", account_ids=["shop_b", "shop_a"])
    assert resolve_auto_pipeline_account_ids(cfg) == ["shop_b", "shop_a"]
    assert cfg.account_id == "shop_b"


def test_dedup_key_multi_store():
    key = _dedup_key(["b", "a"], ["x", "y"])
    assert key == "a|b|x|y"


def test_is_mq_auto_deferred_phase2_row():
    row = SimpleNamespace(meta={"mq_auto_deferred_phase2": True})
    assert is_mq_auto_deferred_phase2_row(row)
    row2 = SimpleNamespace(meta={})
    assert not is_mq_auto_deferred_phase2_row(row2)


def test_compute_mq_phase2_due_at_integer_hours():
    completed = datetime(2026, 7, 1, 10, 0, 0)
    row = SimpleNamespace(demo_mode=False, activity_delay_hours=24)
    due = compute_mq_phase2_due_at(row, completed_at=completed)
    assert due == completed + timedelta(hours=24)


@patch("pdd_agent.api.services.pipeline_mq_auto_commerce.release_mq_store_after_phase1")
@patch("pdd_agent.api.services.pipeline_mq_auto_phase2.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_mq_auto_phase2.get_integrated_pipeline")
def test_handle_mq_lt_fail_records_skip_activity(mock_get, mock_update, mock_release):
    row = SimpleNamespace(
        pipeline_id="p1",
        account_id="shop_a",
        demo_mode=False,
        activity_delay_hours=24,
        current_step="limited_time_queued",
        meta={"mq_auto_deferred_phase2": True},
    )
    mock_get.return_value = row
    mock_release.return_value = {"released": True}
    advance = MagicMock()
    assert handle_mq_auto_limited_time_finished(
        row,
        run_id="lt1",
        success=False,
        error="限时失败",
        advance_store_sequential_fn=advance,
    )
    mock_update.assert_called_once()
    kwargs = mock_update.call_args.kwargs
    assert kwargs["current_step"] == STEP_WAITING
    assert kwargs["meta_patch"]["mq_skip_activity"] is True
    assert kwargs["meta_patch"]["limited_time_outcome"] == "failed"
    advance.assert_called_once()
    mock_release.assert_called_once()


@patch("pdd_agent.api.services.pipeline_mq_auto_phase2.start_mq_phase2")
def test_tick_mq_auto_phase2_defers_when_account_busy(mock_start):
    mock_start.return_value = {
        "pipeline_id": "p1",
        "started": False,
        "deferred": True,
        "reason": "queue_pending",
        "detail": "queued_tasks=2",
    }
    with patch("pdd_agent.api.services.pipeline_mq_auto_phase2.find_mq_phase2_running_pipeline", return_value=None):
        with patch(
            "pdd_agent.api.services.pipeline_mq_auto_phase2.list_mq_auto_phase2_due_pipelines",
            return_value=[SimpleNamespace(pipeline_id="p1", account_id="shop_a", meta={})],
        ):
            with patch("pdd_agent.api.services.pipeline_mq_auto_commerce.record_mq_phase2_wait_for_account_idle"):
                summary = tick_mq_auto_phase2(limit=1)
    assert summary["processed"] == 0
    assert len(summary["deferred"]) == 1
    assert summary["deferred"][0]["reason"] == "queue_pending"


@patch("pdd_agent.api.services.pipeline_mq_auto_commerce.assess_mq_phase2_account_idle")
@patch("pdd_agent.api.services.pipeline_service._enqueue_pipeline_traffic")
@patch("pdd_agent.api.services.pipeline_mq_auto_phase2.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_mq_auto_phase2.get_integrated_pipeline")
def test_start_mq_phase2_promotion_only(mock_get, mock_update, mock_traffic, mock_assess):
    mock_assess.return_value = {"ready": True, "reason": "", "detail": ""}
    row = SimpleNamespace(
        pipeline_id="p1",
        account_id="shop_a",
        auto_promotion=True,
        meta={"mq_skip_activity": True, "limited_time_skip_reason": "限时失败"},
    )
    mock_get.return_value = row
    result = start_mq_phase2(row)
    assert result["mode"] == "promotion_only"
    mock_traffic.assert_called_once()


@patch("pdd_agent.api.services.pipeline_mq_auto_phase2.start_mq_phase2")
@patch("pdd_agent.api.services.pipeline_mq_auto_phase2.find_mq_phase2_running_pipeline")
@patch("pdd_agent.api.services.pipeline_mq_auto_phase2.list_mq_auto_phase2_due_pipelines")
def test_tick_mq_auto_phase2_serial(mock_due, mock_running, mock_start):
    mock_running.return_value = None
    mock_due.return_value = [SimpleNamespace(pipeline_id="p1")]
    mock_start.return_value = {"pipeline_id": "p1", "mode": "activity_then_promotion"}
    summary = tick_mq_auto_phase2(limit=1)
    assert summary["processed"] == 1
    mock_start.assert_called_once()

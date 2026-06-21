"""整合链路状态与浏览器关闭识别测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_issue_report_service import (
    ingest_queue_task_outcome,
    _normalize_listing_reason,
)
from pdd_agent.api.services.pipeline_service import _reconcile_stuck_pipeline_row
from pdd_agent.domain.enums import AgentKind, RunStatus
from pdd_agent.skills.listing.upload import _classify_exception


def test_classify_manual_browser_close():
    exc = RuntimeError("Target page, context or browser has been closed")
    reason, retryable = _classify_exception(exc)
    assert reason == "browser_manually_closed"
    assert retryable is False


def test_classify_timeout_still_transient():
    exc = RuntimeError("[store_A] 超时未出现可点击的「立即使用」，页面 AI 标题填充失败")
    reason, retryable = _classify_exception(exc)
    assert reason == "browser_transient_error"
    assert retryable is True


def test_normalize_listing_reason_manual_close():
    assert _normalize_listing_reason(
        "browser_transient_error",
        "Target page, context or browser has been closed",
    ) == "browser_manually_closed"


@patch("pdd_agent.api.services.pipeline_service.get_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline")
@patch("pdd_agent.api.services.pipeline_service.TaskRunStore")
def test_reconcile_stuck_pipeline_when_listing_failed(mock_store_cls, mock_update, mock_get):
    row = MagicMock()
    row.pipeline_id = "pipe_1"
    row.status = "running"
    row.listing_run_id = "run_list_1"
    row.campaign_run_id = ""
    row.traffic_run_id = ""

    record = MagicMock()
    record.status = RunStatus.FAILED
    record.message = "上架失败：浏览器被关闭"
    mock_store_cls.return_value.load.return_value = record
    refreshed = MagicMock(pipeline_id="pipe_1", status="failed")
    mock_update.return_value = refreshed
    mock_get.return_value = refreshed

    updated = _reconcile_stuck_pipeline_row(row)
    mock_update.assert_called_once()
    mock_get.assert_called_once_with("pipe_1")
    assert updated.status == "failed"


@patch("pdd_agent.api.services.pipeline_issue_report_service.record_pipeline_issue")
def test_ingest_manual_browser_close_critical(mock_record):
    mock_record.return_value = "iss_1"
    ingest_queue_task_outcome(
        pipeline_row=MagicMock(pipeline_id="pipe_1", account_id="store_A", activity_id="", meta={}),
        pipeline_id="pipe_1",
        agent=AgentKind.LISTING.value,
        run_id="run_1",
        success=False,
        result={
            "results": [
                {
                    "status": "failed",
                    "reason": "browser_manually_closed",
                    "error": "Target page, context or browser has been closed",
                    "listing_label": "BD720/第一套图/BD720B",
                }
            ]
        },
        error="Target page, context or browser has been closed",
    )
    kwargs = mock_record.call_args.kwargs
    assert kwargs["reason_code"] == "browser_manually_closed"
    assert kwargs["severity"] == "critical"
    assert kwargs["title"] == "浏览器被手动关闭"

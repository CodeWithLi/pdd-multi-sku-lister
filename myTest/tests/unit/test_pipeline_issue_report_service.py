"""整合链路报错记录服务单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_issue_report_service import (
    ingest_queue_task_outcome,
    issue_to_dict,
    record_pipeline_issue,
)
from pdd_agent.domain.enums import AgentKind


def _pipeline_row(**kwargs):
    row = MagicMock()
    row.pipeline_id = kwargs.get("pipeline_id", "pipe_1")
    row.account_id = kwargs.get("account_id", "store_A")
    row.activity_id = kwargs.get("activity_id", "20981")
    row.meta = kwargs.get("meta", {"batch_id": "batch_1", "activity_ids": ["20981"], "campaign_activity_index": 0})
    return row


@patch("pdd_agent.api.services.pipeline_issue_report_service.insert_pipeline_issue_report")
@patch("pdd_agent.api.services.pipeline_issue_report_service.is_database_available", return_value=True)
def test_record_pipeline_issue_persists(mock_db_ok, mock_insert):
    mock_insert.return_value = MagicMock(issue_id="iss_1")
    issue_id = record_pipeline_issue(
        pipeline_id="pipe_1",
        account_id="store_A",
        stage="listing",
        reason_code="preflight_no_skus",
        title="SKU 编码无效",
        message="找不到对应商品编码 BD999",
        error_text="preflight_no_skus",
    )
    assert issue_id
    mock_insert.assert_called_once()
    kwargs = mock_insert.call_args.kwargs
    assert kwargs["pipeline_id"] == "pipe_1"
    assert kwargs["stage"] == "listing"
    assert kwargs["reason_code"] == "preflight_no_skus"


@patch("pdd_agent.api.services.pipeline_issue_report_service.record_pipeline_issue")
def test_ingest_listing_failed_item(mock_record):
    mock_record.return_value = "iss_1"
    result = ingest_queue_task_outcome(
        pipeline_row=_pipeline_row(),
        pipeline_id="pipe_1",
        agent=AgentKind.LISTING.value,
        run_id="run_1",
        success=False,
        result={
            "results": [
                {
                    "status": "failed",
                    "reason": "preflight_no_skus",
                    "error": "SKU BD999A 在商品表中不存在",
                    "step": "preflight",
                    "product_code": "BD999A",
                    "listing_label": "BD999/第一套图/BD999A",
                }
            ]
        },
        error="listing failed",
    )
    assert result == ["iss_1"]
    mock_record.assert_called()
    kwargs = mock_record.call_args.kwargs
    assert kwargs["stage"] == "listing"
    assert kwargs["product_selector"] == "BD999/第一套图/BD999A"


@patch("pdd_agent.api.services.pipeline_issue_report_service.record_pipeline_issue")
def test_ingest_campaign_skip_as_warning(mock_record):
    mock_record.return_value = "iss_2"
    ingest_queue_task_outcome(
        pipeline_row=_pipeline_row(),
        pipeline_id="pipe_1",
        agent=AgentKind.CAMPAIGN.value,
        run_id="run_2",
        success=False,
        result={
            "results": [
                {
                    "status": "failed",
                    "step": "product_time_requirement_not_met",
                    "error": "商品上架未满 1 天",
                }
            ]
        },
        error="商品上架未满 1 天",
    )
    kwargs = mock_record.call_args.kwargs
    assert kwargs["severity"] == "warning"
    assert kwargs["stage"] == "campaign"
    assert kwargs["activity_id"] == "20981"


@patch("pdd_agent.api.services.pipeline_issue_report_service.record_pipeline_issue")
def test_ingest_browser_closed_critical(mock_record):
    mock_record.return_value = "iss_3"
    ingest_queue_task_outcome(
        pipeline_row=_pipeline_row(),
        pipeline_id="pipe_1",
        agent=AgentKind.TRAFFIC.value,
        run_id="run_3",
        success=False,
        result={"error": "Target page, context or browser has been closed"},
        error="Target page, context or browser has been closed",
    )
    kwargs = mock_record.call_args.kwargs
    assert kwargs["reason_code"] == "browser_manually_closed"
    assert kwargs["severity"] == "critical"


def test_issue_to_dict_stage_label():
    row = MagicMock()
    row.issue_id = "iss_1"
    row.pipeline_id = "pipe_1"
    row.batch_id = ""
    row.account_id = "store_A"
    row.stage = "listing"
    row.chain_step = "preflight"
    row.severity = "error"
    row.reason_code = "preflight_no_skus"
    row.title = "SKU 编码无效"
    row.message = "test"
    row.error_text = "test"
    row.context = {}
    row.run_id = ""
    row.activity_id = ""
    row.product_selector = ""
    row.source_location = ""
    row.created_at = None
    data = issue_to_dict(row)
    assert data["stage_label"] == "上架"

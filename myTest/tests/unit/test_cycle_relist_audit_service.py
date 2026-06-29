"""循环上架审计：轮询快照与处理结果落库。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.api.services.cycle_relist_audit_service import (
    action_log_to_dict,
    poll_log_to_dict,
    record_cycle_relist_action,
    record_cycle_relist_poll,
)


def test_record_cycle_relist_poll_returns_poll_log_id():
    row = MagicMock()
    row.poll_log_id = "poll123"
    with patch(
        "pdd_agent.api.services.cycle_relist_audit_service.create_failure_cycle_relist_poll_log",
        return_value=row,
    ):
        poll_id = record_cycle_relist_poll(
            candidate_total=3,
            new_count=1,
            candidates=[{"record_id": "r1", "merchant_code": "A"}],
            new_candidates=[{"record_id": "r1", "merchant_code": "A"}],
        )
    assert poll_id == "poll123"


def test_record_cycle_relist_action_swallows_db_errors():
    with patch(
        "pdd_agent.api.services.cycle_relist_audit_service.create_failure_cycle_relist_action_log",
        side_effect=RuntimeError("db down"),
    ):
        record_cycle_relist_action(
            record_id="rec1",
            status="started",
            message="ok",
        )


def test_action_log_to_dict_formats_fields():
    row = MagicMock()
    row.action_at = None
    row.feishu_record_id = "rec1"
    row.merchant_code = "BD001"
    row.account_name = "店铺A"
    row.failure_reason = "定价为空"
    row.status = "started"
    row.message = "已启动"
    row.pipeline_id = "pipe1"
    row.trigger_source = "auto_watch"
    data = action_log_to_dict(row)
    assert data["record_id"] == "rec1"
    assert data["merchant_code"] == "BD001"
    assert data["account_name"] == "店铺A"
    assert data["status"] == "started"


def test_poll_log_to_dict_includes_candidates():
    row = MagicMock()
    row.poll_log_id = "poll1"
    row.polled_at = None
    row.candidate_total = 2
    row.new_count = 1
    row.fetch_mode = "search"
    row.fetch_page_size = 50
    row.table_id = "tbl"
    row.table_name = "失败表"
    row.candidates = [{"record_id": "r1"}]
    row.new_candidates = []
    data = poll_log_to_dict(row)
    assert data["poll_log_id"] == "poll1"
    assert data["candidate_total"] == 2
    assert len(data["candidates"]) == 1

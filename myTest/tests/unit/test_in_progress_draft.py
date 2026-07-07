"""日报「正在解决/优化中」半自动草稿单元测试。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from pdd_agent.integrations.wecom.in_progress_draft import (
    collect_in_progress_draft_lines,
    merge_in_progress_lines,
    resolve_pdd_in_progress,
)


def test_merge_in_progress_lines_manual_priority():
    merged = merge_in_progress_lines(
        "修复上架超时",
        ["上架：提交异常（兔兔潮玩屋）", "活动：报名失败"],
    )
    assert merged.splitlines() == [
        "修复上架超时",
        "上架：提交异常（兔兔潮玩屋）",
        "活动：报名失败",
    ]


def test_merge_in_progress_lines_empty_manual_uses_auto():
    merged = merge_in_progress_lines("", ["上架：提交异常"])
    assert merged == "上架：提交异常"


def test_collect_in_progress_draft_lines(monkeypatch):
    row = SimpleNamespace(
        stage="listing",
        account_id="store_A",
        title="提交异常",
        reason_code="submit_exception",
        message="",
        product_selector="BD001/第一套图",
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.wecom.in_progress_draft.is_database_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.wecom.in_progress_draft.list_pipeline_issue_reports_between",
        lambda **kwargs: [row],
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.wecom.in_progress_draft.resolve_account_display_name",
        lambda account_id: "兔兔潮玩屋",
    )
    lines = collect_in_progress_draft_lines(
        window_start=datetime(2026, 7, 5, 18, 1),
        window_end=datetime(2026, 7, 6, 18, 0),
    )
    assert lines == ["上架：提交异常（兔兔潮玩屋） · BD001/第一套图"]


def test_resolve_pdd_in_progress(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.wecom.in_progress_draft.collect_in_progress_draft_lines",
        lambda **kwargs: ["推广：预算设置失败"],
    )
    merged, auto = resolve_pdd_in_progress(
        manual="",
        window_start=datetime(2026, 7, 5, 18, 1),
        window_end=datetime(2026, 7, 6, 18, 0),
    )
    assert merged == "推广：预算设置失败"
    assert auto == ["推广：预算设置失败"]

"""Tests for Feishu field display helpers (process status mirror)."""

from __future__ import annotations

from pdd_agent.integrations.feishu.field_display import (
    format_plain_text,
    format_user_names,
    resolve_process_status,
)


def test_resolve_process_status_from_mirror():
    status = resolve_process_status(mirror_text="已处理完成")
    assert status == {"label": "已处理完成", "source": "mirror_text"}


def test_resolve_process_status_empty_mirror():
    status = resolve_process_status(mirror_text="")
    assert status == {"label": "未同步", "source": "empty"}


def test_format_plain_text_from_rich_text():
    assert format_plain_text([{"text": "已结束", "type": "text"}]) == "已结束"


def test_format_user_names():
    assert format_user_names([{"name": "于跃"}, {"name": "刘一江"}]) == "于跃、刘一江"

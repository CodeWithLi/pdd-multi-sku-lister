"""Git 日报采集与 LLM 摘要单元测试。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from pdd_agent.integrations.git.digest import (
    GitCommitRecord,
    _parse_commit_blocks,
    collect_commits_for_day,
    commits_to_context,
    resolve_git_repo_path,
)
from pdd_agent.integrations.wecom.daily_report import build_daily_report_message


SAMPLE_LOG = """===COMMIT===
abc123fullhash
abc123
CodeWithLi
2026-07-06 10:16:00 +0800
feat(listing): 添加商品属性自动填写功能
feat(listing): 添加商品属性自动填写功能

- 新增 listing_product_attributes_fill 模块
- 添加单元测试
"""


def test_parse_commit_blocks_strips_duplicate_subject():
    commits = _parse_commit_blocks(SAMPLE_LOG)
    assert len(commits) == 1
    commit = commits[0]
    assert commit.short_hash == "abc123"
    assert commit.subject == "feat(listing): 添加商品属性自动填写功能"
    assert "listing_product_attributes_fill" in commit.body
    assert "feat(listing)" not in commit.body.splitlines()[0]


def test_commits_to_context_empty():
    assert "无 Git 提交" in commits_to_context([])


def test_build_daily_report_message_template():
    message = build_daily_report_message(
        progress_summary="商品属性自动填写功能\n商品属性管理功能",
        store_progress="兔兔潮玩屋：已发布16个",
    )
    assert message.startswith("当日已完成交付技术项目进展:")
    assert "商品属性自动填写功能" in message
    assert "兔兔潮玩屋：已发布16个" in message
    assert "-------" in message
    assert "店铺今日发布商品进度：" in message
    assert "----------" in message
    assert message.endswith("正在解决/优化中：")


def test_resolve_git_repo_path_finds_workspace_root():
    path = resolve_git_repo_path()
    assert path.is_dir()
    assert (path / ".git").exists()


def test_collect_commits_for_day_today(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.git.digest._run_git",
        lambda repo, *args: SAMPLE_LOG if "log" in args else "",
    )
    repo = resolve_git_repo_path()
    commits = collect_commits_for_day(repo_path=repo, day=date(2026, 7, 6), include_file_stats=False)
    assert len(commits) == 1
    assert commits[0].author == "CodeWithLi"


def test_summarize_commits_as_progress(monkeypatch):
    from pdd_agent.integrations.git.summarize import summarize_commits_as_progress

    fake_resp = MagicMock()
    fake_resp.content = "商品属性自动填写功能交付\n商品属性管理功能上线"
    fake_model = MagicMock()
    fake_model.invoke.return_value = fake_resp
    monkeypatch.setattr(
        "pdd_agent.integrations.git.summarize.create_chat_model",
        lambda **kwargs: fake_model,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.git.summarize.get_env_settings",
        lambda: MagicMock(llm_api_key="test-key"),
    )

    commits = [
        GitCommitRecord(
            full_hash="abc",
            short_hash="abc",
            author="CodeWithLi",
            committed_at="2026-07-06 10:16:00 +0800",
            subject="feat(listing): 添加商品属性自动填写功能",
            body="- 新增模块",
        )
    ]
    summary = summarize_commits_as_progress(commits)
    assert "商品属性自动填写功能交付" in summary
    fake_model.invoke.assert_called_once()

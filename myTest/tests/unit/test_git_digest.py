"""Git 日报采集与 LLM 摘要单元测试。"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from pdd_agent.integrations.git.digest import (
    GitCommitRecord,
    _parse_commit_blocks,
    collect_commits_for_day,
    commits_to_context,
    resolve_git_repo_path,
)
from pdd_agent.integrations.wecom.daily_report_format import build_daily_report_markdown


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


def test_build_pdd_daily_report_markdown():
    message = build_daily_report_markdown(
        platform="pdd",
        report_date="2026-07-06",
        progress_summary="商品属性自动填写功能\n商品属性管理功能",
        store_progress="兔兔潮玩屋：已发布16个",
        in_progress="修复上架超时问题",
        listing_window="07-05 18:01 ~ 07-06 18:00",
        git_window="07-05 18:01 ~ 07-06 18:00",
    )
    assert "## 日报 · PDD" in message
    assert "### 当日已完成交付技术项目进展" in message
    assert "Git 统计窗口" in message
    assert "- 商品属性自动填写功能" in message
    assert "### 店铺今日发布商品进度" in message
    assert "兔兔潮玩屋：已发布16个" in message
    assert "### 正在解决 / 优化中" in message
    assert "修复上架超时问题" in message
    assert "网盘素材" not in message


def test_build_taobao_daily_report_markdown():
    message = build_daily_report_markdown(
        platform="taobao",
        report_date="2026-07-06",
        netdisk_materials="今日上传素材 120 个",
        in_progress="优化标题生成",
    )
    assert "## 日报 · 淘宝" in message
    assert "### 网盘素材和上架累计数据" in message
    assert "今日上传素材 120 个" in message
    assert "### 正在解决 / 优化中" in message


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


def test_collect_commits_between(monkeypatch):
    captured: dict[str, str] = {}

    def fake_git(repo, *args):
        if "log" in args:
            captured["args"] = " ".join(args)
            return SAMPLE_LOG
        return ""

    monkeypatch.setattr("pdd_agent.integrations.git.digest._run_git", fake_git)
    from pdd_agent.integrations.git.digest import collect_commits_between

    repo = resolve_git_repo_path()
    commits = collect_commits_between(
        repo_path=repo,
        start=datetime(2026, 7, 5, 18, 1, 0),
        end=datetime(2026, 7, 6, 18, 0, 0),
        include_file_stats=False,
    )
    assert len(commits) == 1
    assert "--since=2026-07-05 18:01:00 +0800" in captured["args"]
    assert "--until=2026-07-06 18:00:01 +0800" in captured["args"]


def test_clean_progress_lines_dedupes_and_caps():
    from pdd_agent.integrations.git.summarize import _clean_progress_lines

    text = "\n".join(
        [
            "企业微信日报功能",
            "企业微信日报功能",
            "- 商品属性功能",
            "条目3",
            "条目4",
            "条目5",
            "条目6",
            "条目7",
        ]
    )
    lines = _clean_progress_lines(text)
    assert lines == [
        "企业微信日报功能",
        "商品属性功能",
        "条目3",
        "条目4",
        "条目5",
        "条目6",
    ]


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
    summary, from_cache = summarize_commits_as_progress(commits)
    assert "商品属性自动填写功能交付" in summary
    assert from_cache is False
    fake_model.invoke.assert_called_once()


def test_summarize_commits_as_progress_cache_hit(monkeypatch):
    from datetime import date, datetime

    from pdd_agent.integrations.git.summarize import summarize_commits_as_progress

    cached = MagicMock()
    cached.summary = "企业微信日报功能"
    monkeypatch.setattr(
        "pdd_agent.integrations.git.summarize.is_database_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.git.summarize.get_wecom_git_digest_cache",
        lambda key: cached,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.git.summarize.create_chat_model",
        lambda **kwargs: MagicMock(),
    )

    commits = [
        GitCommitRecord(
            full_hash="abc",
            short_hash="abc",
            author="CodeWithLi",
            committed_at="2026-07-06 10:16:00 +0800",
            subject="feat: wecom",
            body="",
        )
    ]
    summary, from_cache = summarize_commits_as_progress(
        commits,
        report_date=date(2026, 7, 6),
        window_start=datetime(2026, 7, 5, 18, 1),
        window_end=datetime(2026, 7, 6, 18, 0),
    )
    assert summary == "企业微信日报功能"
    assert from_cache is True

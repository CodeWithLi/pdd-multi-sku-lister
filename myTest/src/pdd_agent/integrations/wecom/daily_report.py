"""企业微信日报消息组装。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pdd_agent.integrations.git.digest import (
    GitCommitRecord,
    collect_commits_for_day,
    resolve_git_repo_path,
    today_in_tz,
)
from pdd_agent.integrations.git.summarize import summarize_commits_as_progress
from pdd_agent.integrations.wecom.store_progress import (
    StoreListingSummary,
    collect_pdd_store_progress,
)


@dataclass
class DailyReportDraft:
    report_date: str
    repo_path: str
    commit_count: int
    progress_summary: str
    store_progress: str
    listing_window_start: str
    listing_window_end: str
    store_summaries: list[StoreListingSummary] = field(default_factory=list)
    message: str = ""
    commits: list[GitCommitRecord] = field(default_factory=list)


def build_daily_report_message(
    *,
    progress_summary: str,
    store_progress: str = "",
    in_progress: str = "",
) -> str:
    """按固定模板组装日报文本。"""
    progress = (progress_summary or "今日暂无代码提交").strip()
    store_block = store_progress.strip()
    wip_block = in_progress.strip()

    parts = [
        "当日已完成交付技术项目进展:",
        progress,
        "-------",
        "店铺今日发布商品进度：",
    ]
    if store_block:
        parts.append(store_block)
    parts.extend(
        [
            "----------",
            "正在解决/优化中：",
        ]
    )
    if wip_block:
        parts.append(wip_block)
    return "\n".join(parts)


def generate_daily_report_draft(
    *,
    repo_path: str = "",
    day: date | None = None,
    in_progress: str = "",
) -> DailyReportDraft:
    """采集 Git 提交 + PDD 店铺发布进度，组装日报草稿。"""
    resolved = resolve_git_repo_path(repo_path)
    target_day = day or today_in_tz()
    commits = collect_commits_for_day(repo_path=resolved, day=target_day)
    progress_summary = summarize_commits_as_progress(commits)
    store_snapshot = collect_pdd_store_progress(reference_day=target_day)
    message = build_daily_report_message(
        progress_summary=progress_summary,
        store_progress=store_snapshot.text,
        in_progress=in_progress,
    )
    return DailyReportDraft(
        report_date=target_day.isoformat(),
        repo_path=str(resolved),
        commit_count=len(commits),
        progress_summary=progress_summary,
        store_progress=store_snapshot.text,
        listing_window_start=store_snapshot.window_start.strftime("%Y-%m-%d %H:%M"),
        listing_window_end=store_snapshot.window_end.strftime("%Y-%m-%d %H:%M"),
        store_summaries=store_snapshot.shops,
        message=message,
        commits=commits,
    )

"""企业微信日报消息组装（分 PDD / 淘宝平台）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pdd_agent.integrations.git.digest import (
    GitCommitRecord,
    collect_commits_for_day,
    resolve_git_repo_path,
    today_in_tz,
)
from pdd_agent.integrations.git.summarize import summarize_commits_as_progress
from pdd_agent.integrations.wecom.daily_content import WecomDailyContent, load_wecom_daily_content
from pdd_agent.integrations.wecom.daily_report_format import build_daily_report_markdown
from pdd_agent.integrations.wecom.store_progress import (
    StoreListingSummary,
    collect_pdd_store_progress,
)

DailyReportPlatform = Literal["pdd", "taobao"]


@dataclass
class DailyReportDraft:
    platform: DailyReportPlatform
    report_date: str
    repo_path: str = ""
    commit_count: int = 0
    progress_summary: str = ""
    store_progress: str = ""
    netdisk_materials: str = ""
    in_progress: str = ""
    listing_window_start: str = ""
    listing_window_end: str = ""
    store_summaries: list[StoreListingSummary] = field(default_factory=list)
    message: str = ""
    commits: list[GitCommitRecord] = field(default_factory=list)


def generate_pdd_daily_report_draft(
    *,
    repo_path: str = "",
    day: date | None = None,
    daily_content: WecomDailyContent | None = None,
) -> DailyReportDraft:
    """生成 PDD 日报草稿（Git + 店铺数据 + 手动区块）。"""
    resolved = resolve_git_repo_path(repo_path)
    target_day = day or today_in_tz()
    content = daily_content or load_wecom_daily_content(day=target_day)
    commits = collect_commits_for_day(repo_path=resolved, day=target_day)
    progress_summary = summarize_commits_as_progress(commits)
    store_snapshot = collect_pdd_store_progress(reference_day=target_day)
    in_progress = str(content.pdd.in_progress or "").strip()
    listing_window = (
        f"{store_snapshot.window_start.strftime('%m-%d %H:%M')} ~ "
        f"{store_snapshot.window_end.strftime('%m-%d %H:%M')}"
    )
    message = build_daily_report_markdown(
        platform="pdd",
        report_date=target_day.isoformat(),
        progress_summary=progress_summary,
        store_progress=store_snapshot.text,
        in_progress=in_progress,
        listing_window=listing_window,
    )
    return DailyReportDraft(
        platform="pdd",
        report_date=target_day.isoformat(),
        repo_path=str(resolved),
        commit_count=len(commits),
        progress_summary=progress_summary,
        store_progress=store_snapshot.text,
        in_progress=in_progress,
        listing_window_start=store_snapshot.window_start.strftime("%Y-%m-%d %H:%M"),
        listing_window_end=store_snapshot.window_end.strftime("%Y-%m-%d %H:%M"),
        store_summaries=store_snapshot.shops,
        message=message,
        commits=commits,
    )


def generate_taobao_daily_report_draft(
    *,
    day: date | None = None,
    daily_content: WecomDailyContent | None = None,
) -> DailyReportDraft:
    """生成淘宝日报草稿（仅手动填写区块）。"""
    target_day = day or today_in_tz()
    content = daily_content or load_wecom_daily_content(day=target_day)
    netdisk_materials = str(content.taobao.netdisk_materials or "").strip()
    in_progress = str(content.taobao.in_progress or "").strip()
    message = build_daily_report_markdown(
        platform="taobao",
        report_date=target_day.isoformat(),
        netdisk_materials=netdisk_materials,
        in_progress=in_progress,
    )
    return DailyReportDraft(
        platform="taobao",
        report_date=target_day.isoformat(),
        netdisk_materials=netdisk_materials,
        in_progress=in_progress,
        message=message,
    )


def generate_daily_report_draft(
    *,
    platform: DailyReportPlatform = "pdd",
    repo_path: str = "",
    day: date | None = None,
    daily_content: WecomDailyContent | None = None,
) -> DailyReportDraft:
    if platform == "taobao":
        return generate_taobao_daily_report_draft(day=day, daily_content=daily_content)
    return generate_pdd_daily_report_draft(
        repo_path=repo_path,
        day=day,
        daily_content=daily_content,
    )

"""企业微信日报消息组装（分 PDD / 淘宝平台）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pdd_agent.core.report_time_window import (
    format_report_window_iso,
    format_report_window_label,
    report_listing_window,
    today_in_tz,
)
from pdd_agent.integrations.git.digest import (
    GitCommitRecord,
    collect_commits_between,
    resolve_git_repo_path,
)
from pdd_agent.integrations.git.summarize import summarize_commits_as_progress
from pdd_agent.integrations.wecom.daily_content import (
    WecomDailyContent,
    format_saved_window_label,
    has_saved_pdd_preview,
    load_wecom_daily_content,
)
from pdd_agent.integrations.wecom.daily_report_format import build_daily_report_markdown
from pdd_agent.integrations.wecom.in_progress_draft import resolve_pdd_in_progress
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
    progress_summary_from_cache: bool = False
    store_progress: str = ""
    netdisk_materials: str = ""
    in_progress: str = ""
    in_progress_manual: str = ""
    in_progress_auto_draft: str = ""
    listing_window_start: str = ""
    listing_window_end: str = ""
    git_window_start: str = ""
    git_window_end: str = ""
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
    window_start, window_end = report_listing_window(reference_day=target_day)
    git_window_label = format_report_window_label(window_start, window_end)
    listing_window_start, listing_window_end = format_report_window_iso(window_start, window_end)

    commits = collect_commits_between(
        repo_path=resolved,
        start=window_start,
        end=window_end,
        inclusive_end=True,
    )
    progress_summary, from_cache = summarize_commits_as_progress(
        commits,
        report_date=target_day,
        window_start=window_start,
        window_end=window_end,
    )
    store_snapshot = collect_pdd_store_progress(reference_day=target_day)
    manual_in_progress = str(content.pdd.in_progress or "").strip()
    in_progress, auto_draft = resolve_pdd_in_progress(
        manual=manual_in_progress,
        window_start=window_start,
        window_end=window_end,
    )
    progress_summary_out = progress_summary
    store_progress_out = store_snapshot.text
    in_progress_out = in_progress
    git_window_start_out = listing_window_start
    git_window_end_out = listing_window_end
    if has_saved_pdd_preview(content):
        progress_summary_out = str(content.pdd.progress_summary or progress_summary)
        store_progress_out = str(content.pdd.store_progress or store_snapshot.text)
        in_progress_out = str(content.pdd.in_progress or in_progress)
        if content.pdd.listing_window_start and content.pdd.listing_window_end:
            listing_window_start = content.pdd.listing_window_start
            listing_window_end = content.pdd.listing_window_end
        if content.pdd.git_window_start and content.pdd.git_window_end:
            git_window_start_out = content.pdd.git_window_start
            git_window_end_out = content.pdd.git_window_end
        git_window_label = format_saved_window_label(
            git_window_start_out,
            git_window_end_out,
        ) or git_window_label
    listing_window = format_saved_window_label(listing_window_start, listing_window_end) or git_window_label
    message = build_daily_report_markdown(
        platform="pdd",
        report_date=target_day.isoformat(),
        progress_summary=progress_summary_out,
        store_progress=store_progress_out,
        in_progress=in_progress_out,
        listing_window=listing_window,
        git_window=git_window_label,
    )
    return DailyReportDraft(
        platform="pdd",
        report_date=target_day.isoformat(),
        repo_path=str(resolved),
        commit_count=len(commits),
        progress_summary=progress_summary_out,
        progress_summary_from_cache=from_cache,
        store_progress=store_progress_out,
        in_progress=in_progress_out,
        in_progress_manual=manual_in_progress,
        in_progress_auto_draft="\n".join(auto_draft),
        listing_window_start=listing_window_start,
        listing_window_end=listing_window_end,
        git_window_start=git_window_start_out,
        git_window_end=git_window_end_out,
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
        in_progress_manual=in_progress,
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

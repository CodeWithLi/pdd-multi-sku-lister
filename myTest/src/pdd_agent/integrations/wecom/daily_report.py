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


def _append_section(parts: list[str], title: str, body: str) -> None:
    parts.append(title)
    text = str(body or "").strip()
    if text:
        parts.append(text)


def build_pdd_daily_report_message(
    *,
    progress_summary: str,
    store_progress: str = "",
    in_progress: str = "",
) -> str:
    """PDD 日报：Git 进展 + 店铺发布进度 + 正在解决/优化中（无网盘素材）。"""
    parts: list[str] = []
    _append_section(parts, "当日已完成交付技术项目进展:", progress_summary or "今日暂无代码提交")
    parts.append("-------")
    _append_section(parts, "店铺今日发布商品进度：", store_progress)
    parts.append("----------")
    _append_section(parts, "正在解决/优化中：", in_progress)
    return "\n".join(parts)


def build_taobao_daily_report_message(
    *,
    netdisk_materials: str = "",
    in_progress: str = "",
) -> str:
    """淘宝日报：仅手动填写区块（网盘素材 + 正在解决/优化中）。"""
    parts: list[str] = []
    _append_section(parts, "当日已完成交付技术项目进展:", "")
    parts.append("-------")
    _append_section(parts, "店铺今日发布商品进度：", "")
    parts.append("---------")
    _append_section(parts, "网盘素材和上架累计数据", netdisk_materials)
    parts.append("----------")
    _append_section(parts, "正在解决/优化中：", in_progress)
    return "\n".join(parts)


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
    message = build_pdd_daily_report_message(
        progress_summary=progress_summary,
        store_progress=store_snapshot.text,
        in_progress=in_progress,
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
    message = build_taobao_daily_report_message(
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

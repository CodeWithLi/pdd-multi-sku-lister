"""企业微信日报每日手动填写内容（MySQL 按日存储）。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from pdd_agent.core.report_time_window import format_report_window_label, report_listing_window
from pdd_agent.db.repositories import get_wecom_daily_content_row, upsert_wecom_daily_content_row
from pdd_agent.db.session import is_database_available
from pdd_agent.integrations.wecom.daily_report_format import build_daily_report_markdown
from pdd_agent.integrations.wecom.store_progress import today_in_tz


class PddDailyContent(BaseModel):
    in_progress: str = ""
    progress_summary: str = ""
    store_progress: str = ""
    listing_window_start: str = ""
    listing_window_end: str = ""
    git_window_start: str = ""
    git_window_end: str = ""
    preview_saved: bool = False


class TaobaoDailyContent(BaseModel):
    netdisk_materials: str = ""
    in_progress: str = ""


class WecomDailyContent(BaseModel):
    content_date: str = ""
    pdd: PddDailyContent = Field(default_factory=PddDailyContent)
    taobao: TaobaoDailyContent = Field(default_factory=TaobaoDailyContent)
    updated_at: str = ""


def _resolve_day(day: date | None = None) -> date:
    return day or today_in_tz()


def _empty_content(content_date: date) -> WecomDailyContent:
    return WecomDailyContent(content_date=content_date.isoformat())


def format_saved_window_label(start: str, end: str) -> str:
    s = str(start or "").strip()
    e = str(end or "").strip()
    if not s or not e:
        return ""
    short = lambda value: value[5:] if len(value) > 5 else value
    return f"{short(s)} ~ {short(e)}"


def _row_to_content(row) -> WecomDailyContent:
    updated = row.updated_at
    updated_text = ""
    if isinstance(updated, datetime):
        updated_text = updated.strftime("%Y-%m-%d %H:%M:%S")
    return WecomDailyContent(
        content_date=row.content_date.isoformat(),
        pdd=PddDailyContent(
            in_progress=str(row.pdd_in_progress or ""),
            progress_summary=str(getattr(row, "pdd_progress_summary", "") or ""),
            store_progress=str(getattr(row, "pdd_store_progress", "") or ""),
            listing_window_start=str(getattr(row, "pdd_listing_window_start", "") or ""),
            listing_window_end=str(getattr(row, "pdd_listing_window_end", "") or ""),
            git_window_start=str(getattr(row, "pdd_git_window_start", "") or ""),
            git_window_end=str(getattr(row, "pdd_git_window_end", "") or ""),
            preview_saved=bool(getattr(row, "pdd_preview_saved", False)),
        ),
        taobao=TaobaoDailyContent(
            netdisk_materials=str(row.taobao_netdisk_materials or ""),
            in_progress=str(row.taobao_in_progress or ""),
        ),
        updated_at=updated_text,
    )


def has_saved_pdd_preview(content: WecomDailyContent | None) -> bool:
    if not content or not content.pdd.preview_saved:
        return False
    pdd = content.pdd
    return bool(
        str(pdd.progress_summary or "").strip()
        or str(pdd.store_progress or "").strip()
        or str(pdd.in_progress or "").strip()
    )


def build_saved_pdd_daily_report_message(
    content: WecomDailyContent,
    *,
    report_date: str | None = None,
) -> str:
    """根据已保存的 PDD 预览字段组装 Markdown。"""
    pdd = content.pdd
    listing_window = format_saved_window_label(
        pdd.listing_window_start,
        pdd.listing_window_end,
    )
    git_window = format_saved_window_label(
        pdd.git_window_start or pdd.listing_window_start,
        pdd.git_window_end or pdd.listing_window_end,
    )
    if not listing_window:
        window_start, window_end = report_listing_window(
            reference_day=date.fromisoformat(report_date or content.content_date)
        )
        listing_window = format_report_window_label(window_start, window_end)
        git_window = listing_window
    return build_daily_report_markdown(
        platform="pdd",
        report_date=str(report_date or content.content_date or today_in_tz().isoformat()),
        progress_summary=str(pdd.progress_summary or ""),
        store_progress=str(pdd.store_progress or ""),
        in_progress=str(pdd.in_progress or ""),
        listing_window=listing_window,
        git_window=git_window,
    )


def load_wecom_daily_content(*, day: date | None = None) -> WecomDailyContent:
    """读取指定日期（默认今天）的手动内容；当天无记录则返回空。"""
    target = _resolve_day(day)
    if not is_database_available():
        return _empty_content(target)
    row = get_wecom_daily_content_row(target)
    if not row:
        return _empty_content(target)
    return _row_to_content(row)


def save_wecom_daily_content(
    content: WecomDailyContent,
    *,
    day: date | None = None,
) -> WecomDailyContent:
    """保存指定日期（默认今天）的手动内容；同一天覆盖更新。"""
    if not is_database_available():
        raise RuntimeError("数据库不可用，无法保存日报手动内容")
    target = _resolve_day(day)
    existing = load_wecom_daily_content(day=target)
    merged = WecomDailyContent(
        content_date=target.isoformat(),
        pdd=PddDailyContent(
            in_progress=str(content.pdd.in_progress or existing.pdd.in_progress or ""),
            progress_summary=str(content.pdd.progress_summary or existing.pdd.progress_summary or ""),
            store_progress=str(content.pdd.store_progress or existing.pdd.store_progress or ""),
            listing_window_start=str(
                content.pdd.listing_window_start or existing.pdd.listing_window_start or ""
            ),
            listing_window_end=str(
                content.pdd.listing_window_end or existing.pdd.listing_window_end or ""
            ),
            git_window_start=str(content.pdd.git_window_start or existing.pdd.git_window_start or ""),
            git_window_end=str(content.pdd.git_window_end or existing.pdd.git_window_end or ""),
            preview_saved=bool(content.pdd.preview_saved or existing.pdd.preview_saved),
        ),
        taobao=TaobaoDailyContent(
            netdisk_materials=str(
                content.taobao.netdisk_materials or existing.taobao.netdisk_materials or ""
            ),
            in_progress=str(content.taobao.in_progress or existing.taobao.in_progress or ""),
        ),
    )
    row = upsert_wecom_daily_content_row(
        content_date=target,
        pdd_in_progress=merged.pdd.in_progress,
        pdd_progress_summary=merged.pdd.progress_summary,
        pdd_store_progress=merged.pdd.store_progress,
        pdd_listing_window_start=merged.pdd.listing_window_start,
        pdd_listing_window_end=merged.pdd.listing_window_end,
        pdd_git_window_start=merged.pdd.git_window_start,
        pdd_git_window_end=merged.pdd.git_window_end,
        pdd_preview_saved=merged.pdd.preview_saved,
        taobao_netdisk_materials=merged.taobao.netdisk_materials,
        taobao_in_progress=merged.taobao.in_progress,
    )
    if not row:
        raise RuntimeError("保存日报手动内容失败")
    return _row_to_content(row)


def save_wecom_daily_preview(
    *,
    progress_summary: str = "",
    store_progress: str = "",
    in_progress: str = "",
    listing_window_start: str = "",
    listing_window_end: str = "",
    git_window_start: str = "",
    git_window_end: str = "",
    day: date | None = None,
) -> WecomDailyContent:
    """保存 PDD 日报预览编辑内容（供定时发送使用）；整段覆盖，允许清空字段。"""
    if not is_database_available():
        raise RuntimeError("数据库不可用，无法保存日报预览")
    target = _resolve_day(day)
    existing = load_wecom_daily_content(day=target)
    row = upsert_wecom_daily_content_row(
        content_date=target,
        pdd_in_progress=str(in_progress or ""),
        pdd_progress_summary=str(progress_summary or ""),
        pdd_store_progress=str(store_progress or ""),
        pdd_listing_window_start=str(listing_window_start or ""),
        pdd_listing_window_end=str(listing_window_end or ""),
        pdd_git_window_start=str(git_window_start or ""),
        pdd_git_window_end=str(git_window_end or ""),
        pdd_preview_saved=True,
        taobao_netdisk_materials=str(existing.taobao.netdisk_materials or ""),
        taobao_in_progress=str(existing.taobao.in_progress or ""),
    )
    if not row:
        raise RuntimeError("保存日报预览失败")
    return _row_to_content(row)

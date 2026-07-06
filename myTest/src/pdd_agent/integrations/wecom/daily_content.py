"""企业微信日报每日手动填写内容（MySQL 按日存储）。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from pdd_agent.db.repositories import get_wecom_daily_content_row, upsert_wecom_daily_content_row
from pdd_agent.db.session import is_database_available
from pdd_agent.integrations.wecom.store_progress import today_in_tz


class PddDailyContent(BaseModel):
    in_progress: str = ""


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


def _row_to_content(row) -> WecomDailyContent:
    updated = row.updated_at
    updated_text = ""
    if isinstance(updated, datetime):
        updated_text = updated.strftime("%Y-%m-%d %H:%M:%S")
    return WecomDailyContent(
        content_date=row.content_date.isoformat(),
        pdd=PddDailyContent(in_progress=str(row.pdd_in_progress or "")),
        taobao=TaobaoDailyContent(
            netdisk_materials=str(row.taobao_netdisk_materials or ""),
            in_progress=str(row.taobao_in_progress or ""),
        ),
        updated_at=updated_text,
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
    row = upsert_wecom_daily_content_row(
        content_date=target,
        pdd_in_progress=str(content.pdd.in_progress or ""),
        taobao_netdisk_materials=str(content.taobao.netdisk_materials or ""),
        taobao_in_progress=str(content.taobao.in_progress or ""),
    )
    if not row:
        raise RuntimeError("保存日报手动内容失败")
    return _row_to_content(row)

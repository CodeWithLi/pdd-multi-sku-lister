"""企业微信日报每日手动内容（MySQL）单元测试。"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from pdd_agent.integrations.wecom.daily_content import (
    PddDailyContent,
    TaobaoDailyContent,
    WecomDailyContent,
    build_saved_pdd_daily_report_message,
    has_saved_pdd_preview,
    load_wecom_daily_content,
    save_wecom_daily_content,
    save_wecom_daily_preview,
)


def test_load_wecom_daily_content_empty_when_no_row():
    with patch("pdd_agent.integrations.wecom.daily_content.is_database_available", return_value=True):
        with patch(
            "pdd_agent.integrations.wecom.daily_content.get_wecom_daily_content_row",
            return_value=None,
        ):
            with patch(
                "pdd_agent.integrations.wecom.daily_content.today_in_tz",
                return_value=date(2026, 7, 6),
            ):
                content = load_wecom_daily_content()
    assert content.content_date == "2026-07-06"
    assert content.pdd.in_progress == ""
    assert content.taobao.netdisk_materials == ""


def test_load_wecom_daily_content_returns_today_row_only():
    row = MagicMock()
    row.content_date = date(2026, 7, 6)
    row.pdd_in_progress = "今天处理中"
    row.pdd_progress_summary = "技术进展"
    row.pdd_store_progress = "店铺进度"
    row.pdd_listing_window_start = "2026-07-05 18:01"
    row.pdd_listing_window_end = "2026-07-06 18:00"
    row.pdd_git_window_start = "2026-07-05 18:01"
    row.pdd_git_window_end = "2026-07-06 18:00"
    row.pdd_preview_saved = True
    row.taobao_netdisk_materials = "素材 10 个"
    row.taobao_in_progress = "淘宝优化"
    row.updated_at = datetime(2026, 7, 6, 15, 30, 0)

    with patch("pdd_agent.integrations.wecom.daily_content.is_database_available", return_value=True):
        with patch(
            "pdd_agent.integrations.wecom.daily_content.get_wecom_daily_content_row",
            return_value=row,
        ) as mock_get:
            content = load_wecom_daily_content(day=date(2026, 7, 6))

    mock_get.assert_called_once_with(date(2026, 7, 6))
    assert content.pdd.in_progress == "今天处理中"
    assert content.pdd.progress_summary == "技术进展"
    assert content.pdd.preview_saved is True
    assert content.taobao.netdisk_materials == "素材 10 个"


def test_save_wecom_daily_content_upserts_today():
    row = MagicMock()
    row.content_date = date(2026, 7, 6)
    row.pdd_in_progress = "新内容"
    row.taobao_netdisk_materials = ""
    row.taobao_in_progress = ""
    row.updated_at = datetime(2026, 7, 6, 16, 0, 0)

    with patch("pdd_agent.integrations.wecom.daily_content.is_database_available", return_value=True):
        with patch(
            "pdd_agent.integrations.wecom.daily_content.upsert_wecom_daily_content_row",
            return_value=row,
        ) as mock_upsert:
            with patch(
                "pdd_agent.integrations.wecom.daily_content.today_in_tz",
                return_value=date(2026, 7, 6),
            ):
                saved = save_wecom_daily_content(
                    WecomDailyContent(
                        pdd=PddDailyContent(in_progress="新内容"),
                        taobao=TaobaoDailyContent(),
                    )
                )

    mock_upsert.assert_called_once_with(
        content_date=date(2026, 7, 6),
        pdd_in_progress="新内容",
        pdd_progress_summary="",
        pdd_store_progress="",
        pdd_listing_window_start="",
        pdd_listing_window_end="",
        pdd_git_window_start="",
        pdd_git_window_end="",
        pdd_preview_saved=False,
        taobao_netdisk_materials="",
        taobao_in_progress="",
    )
    assert saved.pdd.in_progress == "新内容"


def test_has_saved_pdd_preview_requires_flag_and_content():
    empty = WecomDailyContent(pdd=PddDailyContent(preview_saved=True))
    assert has_saved_pdd_preview(empty) is False
    saved = WecomDailyContent(
        pdd=PddDailyContent(progress_summary="进展", preview_saved=True),
    )
    assert has_saved_pdd_preview(saved) is True


def test_build_saved_pdd_daily_report_message():
    content = WecomDailyContent(
        content_date="2026-07-06",
        pdd=PddDailyContent(
            progress_summary="企业微信日报功能",
            store_progress="兔兔潮玩屋：已发布 8 个",
            in_progress="优化日报定时",
            listing_window_start="2026-07-05 18:01",
            listing_window_end="2026-07-06 18:00",
            preview_saved=True,
        ),
    )
    message = build_saved_pdd_daily_report_message(content)
    assert "## 日报 · PDD" in message
    assert "企业微信日报功能" in message
    assert "兔兔潮玩屋：已发布 8 个" in message
    assert "优化日报定时" in message


def test_save_wecom_daily_preview_marks_saved():
    row = MagicMock()
    row.content_date = date(2026, 7, 6)
    row.pdd_in_progress = "处理中"
    row.pdd_progress_summary = "进展"
    row.pdd_store_progress = "店铺"
    row.pdd_listing_window_start = ""
    row.pdd_listing_window_end = ""
    row.pdd_git_window_start = ""
    row.pdd_git_window_end = ""
    row.pdd_preview_saved = True
    row.taobao_netdisk_materials = ""
    row.taobao_in_progress = ""
    row.updated_at = datetime(2026, 7, 6, 16, 0, 0)

    with patch("pdd_agent.integrations.wecom.daily_content.is_database_available", return_value=True):
        with patch(
            "pdd_agent.integrations.wecom.daily_content.get_wecom_daily_content_row",
            return_value=None,
        ):
            with patch(
                "pdd_agent.integrations.wecom.daily_content.upsert_wecom_daily_content_row",
                return_value=row,
            ) as mock_upsert:
                with patch(
                    "pdd_agent.integrations.wecom.daily_content.today_in_tz",
                    return_value=date(2026, 7, 6),
                ):
                    saved = save_wecom_daily_preview(
                        progress_summary="进展",
                        store_progress="店铺",
                        in_progress="处理中",
                    )

    assert mock_upsert.call_args.kwargs["pdd_preview_saved"] is True
    assert saved.pdd.preview_saved is True


def test_save_wecom_daily_preview_overwrites_empty_store_progress():
    existing_row = MagicMock()
    existing_row.content_date = date(2026, 7, 10)
    existing_row.pdd_in_progress = "旧进行中"
    existing_row.pdd_progress_summary = "旧进展"
    existing_row.pdd_store_progress = "旧店铺：已发布23个"
    existing_row.pdd_listing_window_start = ""
    existing_row.pdd_listing_window_end = ""
    existing_row.pdd_git_window_start = ""
    existing_row.pdd_git_window_end = ""
    existing_row.pdd_preview_saved = True
    existing_row.taobao_netdisk_materials = ""
    existing_row.taobao_in_progress = ""
    existing_row.updated_at = datetime(2026, 7, 10, 10, 0, 0)

    saved_row = MagicMock()
    saved_row.content_date = date(2026, 7, 10)
    saved_row.pdd_in_progress = "新进行中"
    saved_row.pdd_progress_summary = "新进展"
    saved_row.pdd_store_progress = ""
    saved_row.pdd_listing_window_start = "2026-07-09T18:01:00"
    saved_row.pdd_listing_window_end = "2026-07-10T18:00:00"
    saved_row.pdd_git_window_start = "2026-07-09T18:01:00"
    saved_row.pdd_git_window_end = "2026-07-10T18:00:00"
    saved_row.pdd_preview_saved = True
    saved_row.taobao_netdisk_materials = ""
    saved_row.taobao_in_progress = ""
    saved_row.updated_at = datetime(2026, 7, 10, 17, 0, 0)

    with patch("pdd_agent.integrations.wecom.daily_content.is_database_available", return_value=True):
        with patch(
            "pdd_agent.integrations.wecom.daily_content.get_wecom_daily_content_row",
            return_value=existing_row,
        ):
            with patch(
                "pdd_agent.integrations.wecom.daily_content.upsert_wecom_daily_content_row",
                return_value=saved_row,
            ) as mock_upsert:
                with patch(
                    "pdd_agent.integrations.wecom.daily_content.today_in_tz",
                    return_value=date(2026, 7, 10),
                ):
                    saved = save_wecom_daily_preview(
                        progress_summary="新进展",
                        store_progress="",
                        in_progress="新进行中",
                    )

    assert mock_upsert.call_args.kwargs["pdd_store_progress"] == ""
    assert saved.pdd.store_progress == ""


def test_save_wecom_daily_content_requires_database():
    with patch("pdd_agent.integrations.wecom.daily_content.is_database_available", return_value=False):
        with pytest.raises(RuntimeError, match="数据库不可用"):
            save_wecom_daily_content(WecomDailyContent())

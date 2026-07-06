"""企业微信日报每日手动内容（MySQL）单元测试。"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from pdd_agent.integrations.wecom.daily_content import (
    PddDailyContent,
    TaobaoDailyContent,
    WecomDailyContent,
    load_wecom_daily_content,
    save_wecom_daily_content,
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
        taobao_netdisk_materials="",
        taobao_in_progress="",
    )
    assert saved.pdd.in_progress == "新内容"


def test_save_wecom_daily_content_requires_database():
    with patch("pdd_agent.integrations.wecom.daily_content.is_database_available", return_value=False):
        with pytest.raises(RuntimeError, match="数据库不可用"):
            save_wecom_daily_content(WecomDailyContent())

"""企业微信日报定时调度单元测试。"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from pdd_agent.api.services.wecom_daily_report_scheduler import WecomDailyReportScheduler
from pdd_agent.integrations.wecom.config import WecomConfig


def _cfg(**kwargs) -> WecomConfig:
    return WecomConfig(
        enabled=True,
        webhook_url="https://example.com/webhook?key=abc",
        daily_report_schedule_enabled=True,
        daily_report_schedule_hour=18,
        daily_report_schedule_minute=0,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_scheduler_waits_until_target_time(monkeypatch):
    scheduler = WecomDailyReportScheduler(poll_seconds=0.01)
    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.load_wecom_config",
        lambda: _cfg(),
    )

    fake_now = datetime(2026, 7, 6, 17, 30, 0)
    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.datetime",
        MagicMock(now=lambda tz=None: fake_now),
    )

    send_mock = MagicMock(return_value=True)
    monkeypatch.setattr(scheduler, "_send_daily_report", send_mock)
    scheduler._init_schedule_tracking()

    await scheduler._maybe_send_daily_report()
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_sends_after_target_time(monkeypatch):
    scheduler = WecomDailyReportScheduler(poll_seconds=0.01)
    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.load_wecom_config",
        lambda: _cfg(),
    )

    fake_now = datetime(2026, 7, 6, 18, 5, 0)
    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.datetime",
        MagicMock(now=lambda tz=None: fake_now),
    )

    send_mock = MagicMock(return_value=True)
    monkeypatch.setattr(scheduler, "_send_daily_report", send_mock)
    scheduler._init_schedule_tracking()
    scheduler._seen_before_target_today = True

    await scheduler._maybe_send_daily_report()
    send_mock.assert_called_once()
    assert send_mock.call_args[0][0] == "pdd"
    assert scheduler.last_run_date == date(2026, 7, 6)


def test_trigger_now_sends_custom_message(monkeypatch):
    scheduler = WecomDailyReportScheduler()
    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.load_wecom_config",
        lambda: _cfg(),
    )
    send_report = MagicMock(return_value=True)
    monkeypatch.setattr(scheduler, "_send_daily_report", send_report)

    ok = scheduler.trigger_now("pdd", message="## 自定义日报")

    assert ok is True
    send_report.assert_called_once()
    assert send_report.call_args.kwargs["message"] == "## 自定义日报"
    assert send_report.call_args.kwargs["trigger_kind"] == "manual"


def test_resolve_scheduled_message_uses_saved_preview(monkeypatch):
    scheduler = WecomDailyReportScheduler()
    saved = MagicMock()
    saved.content_date = "2026-07-06"
    saved.pdd.preview_saved = True
    saved.pdd.progress_summary = "已保存进展"
    saved.pdd.store_progress = ""
    saved.pdd.in_progress = ""

    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.load_wecom_daily_content",
        lambda: saved,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.has_saved_pdd_preview",
        lambda content: True,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.build_saved_pdd_daily_report_message",
        lambda content: "## 已保存日报",
    )

    message, draft, saved_content = scheduler._resolve_scheduled_message(
        "pdd",
        _cfg(daily_report_schedule_use_saved_preview=True),
    )

    assert message == "## 已保存日报"
    assert draft is None
    assert saved_content is saved


def test_resolve_scheduled_message_fallback_when_no_saved_preview(monkeypatch):
    scheduler = WecomDailyReportScheduler()
    draft = MagicMock()
    draft.message = "## 实时生成"

    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.has_saved_pdd_preview",
        lambda content: False,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.load_wecom_daily_content",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.wecom_daily_report_scheduler.generate_daily_report_draft",
        lambda **kwargs: draft,
    )

    message, resolved_draft, saved_content = scheduler._resolve_scheduled_message(
        "pdd",
        _cfg(daily_report_schedule_use_saved_preview=True),
    )

    assert message == "## 实时生成"
    assert resolved_draft is draft
    assert saved_content is None

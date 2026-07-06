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

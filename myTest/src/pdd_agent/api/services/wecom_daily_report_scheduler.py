"""企业微信日报定时发送调度（仅 PDD）。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.wecom.client import WecomAPIError, send_markdown
from pdd_agent.integrations.wecom.config import load_wecom_config, wecom_configured
from pdd_agent.integrations.wecom.daily_report import DailyReportPlatform, generate_daily_report_draft

logger = get_logger(__name__)

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    TZ = timezone(timedelta(hours=8))

_scheduler: "WecomDailyReportScheduler | None" = None


def get_wecom_daily_report_scheduler() -> "WecomDailyReportScheduler":
    global _scheduler
    if _scheduler is None:
        _scheduler = WecomDailyReportScheduler()
    return _scheduler


class WecomDailyReportScheduler:
    def __init__(self, poll_seconds: float = 30.0) -> None:
        self._poll_seconds = poll_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_run_date: date | None = None
        self._schedule_track_date: date | None = None
        self._seen_before_target_today = False

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_run_date(self) -> date | None:
        return self._last_run_date

    def _schedule_target(self, now: datetime, cfg) -> datetime:
        return now.replace(
            hour=int(cfg.daily_report_schedule_hour),
            minute=int(cfg.daily_report_schedule_minute),
            second=0,
            microsecond=0,
        )

    def _init_schedule_tracking(self) -> None:
        cfg = load_wecom_config()
        now = datetime.now(TZ)
        self._schedule_track_date = now.date()
        target = self._schedule_target(now, cfg)
        self._seen_before_target_today = now < target

    def reset_last_run_date(self) -> None:
        self._last_run_date = None
        self._init_schedule_tracking()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._init_schedule_tracking()
        self._task = asyncio.create_task(self._loop())
        logger.info("wecom daily report scheduler started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None
        logger.info("wecom daily report scheduler stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._maybe_send_daily_report()
            except Exception:
                logger.exception("wecom daily report scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                continue

    async def _maybe_send_daily_report(self) -> None:
        cfg = load_wecom_config()
        if not cfg.daily_report_schedule_enabled:
            return
        if not wecom_configured(cfg):
            return

        now = datetime.now(TZ)
        if self._schedule_track_date != now.date():
            self._schedule_track_date = now.date()
            self._seen_before_target_today = False

        target = self._schedule_target(now, cfg)
        if now < target:
            self._seen_before_target_today = True
            return
        if self._last_run_date == now.date():
            return
        if not self._seen_before_target_today:
            logger.info(
                "wecom daily report scheduler skip catch-up after restart for %s (schedule=%02d:%02d)",
                now.date().isoformat(),
                int(cfg.daily_report_schedule_hour),
                int(cfg.daily_report_schedule_minute),
            )
            self._last_run_date = now.date()
            return

        ok = await asyncio.to_thread(self._send_daily_report, "pdd", cfg)
        if ok:
            self._last_run_date = now.date()
            print(
                f"[scheduler] 企业微信 PDD 日报已发送，触发时间={now.strftime('%Y-%m-%d %H:%M:%S')}",
                flush=True,
            )

    def _send_daily_report(self, platform: DailyReportPlatform, cfg) -> bool:
        try:
            draft = generate_daily_report_draft(platform=platform)
            send_markdown(draft.message, cfg=cfg)
            logger.info(
                "wecom daily report sent platform=%s commits=%s stores=%s",
                platform,
                draft.commit_count,
                len(draft.store_summaries),
            )
            return True
        except WecomAPIError:
            logger.exception("wecom daily report send failed platform=%s", platform)
            return False
        except Exception:
            logger.exception("wecom daily report generate/send failed platform=%s", platform)
            return False

    def trigger_now(
        self,
        platform: DailyReportPlatform = "pdd",
        *,
        message: str = "",
    ) -> bool:
        """手动触发：发送指定平台日报（可传入已编辑的 Markdown）。"""
        cfg = load_wecom_config()
        if not wecom_configured(cfg):
            raise RuntimeError("企业微信未配置或未启用")
        custom = str(message or "").strip()
        if custom:
            ok = self._send_markdown(custom, platform, cfg)
        else:
            ok = self._send_daily_report(platform, cfg)
        if ok and platform == "pdd":
            self._last_run_date = datetime.now(TZ).date()
        return ok

    def _send_markdown(self, message: str, platform: DailyReportPlatform, cfg) -> bool:
        try:
            send_markdown(message, cfg=cfg)
            logger.info("wecom daily report sent platform=%s custom_message=true", platform)
            return True
        except WecomAPIError:
            logger.exception("wecom daily report send failed platform=%s", platform)
            return False
        except Exception:
            logger.exception("wecom daily report send failed platform=%s", platform)
            return False

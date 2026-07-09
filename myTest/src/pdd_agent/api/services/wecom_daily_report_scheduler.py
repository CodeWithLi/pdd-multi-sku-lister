"""企业微信日报定时发送调度（仅 PDD）。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from pdd_agent.core.logging import get_logger
from pdd_agent.core.report_time_window import report_listing_window
from pdd_agent.integrations.wecom.client import WecomAPIError, send_markdown
from pdd_agent.integrations.wecom.config import (
    daily_report_webhook_configured,
    load_wecom_config,
    resolve_daily_report_webhook_url,
)
from pdd_agent.integrations.wecom.daily_content import (
    build_saved_pdd_daily_report_message,
    has_saved_pdd_preview,
    load_wecom_daily_content,
)
from pdd_agent.integrations.wecom.daily_report import DailyReportPlatform, generate_daily_report_draft
from pdd_agent.integrations.wecom.daily_report_log import record_daily_report_send
from pdd_agent.integrations.wecom.store_progress import today_in_tz

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
        if not daily_report_webhook_configured(cfg):
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

        ok = await asyncio.to_thread(
            self._send_daily_report,
            "pdd",
            cfg,
            trigger_kind="scheduled",
        )
        if ok:
            self._last_run_date = now.date()
            print(
                f"[scheduler] 企业微信 PDD 日报已发送，触发时间={now.strftime('%Y-%m-%d %H:%M:%S')}",
                flush=True,
            )

    def _webhook_target_label(self, cfg) -> str:
        return "daily_report" if str(cfg.webhook_url_daily_report or "").strip() else "default"

    def _record_send(
        self,
        *,
        platform: DailyReportPlatform,
        report_date: date,
        message: str,
        trigger_kind: str,
        ok: bool,
        errcode: int = 0,
        errmsg: str = "",
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        cfg=None,
    ) -> None:
        try:
            record_daily_report_send(
                platform=platform,
                report_date=report_date,
                message=message,
                trigger_kind=trigger_kind,
                ok=ok,
                errcode=errcode,
                errmsg=errmsg,
                window_start=window_start,
                window_end=window_end,
                webhook_target=self._webhook_target_label(cfg or load_wecom_config()),
            )
        except Exception:
            logger.exception("record wecom daily report log failed platform=%s", platform)

    def _resolve_scheduled_message(
        self, platform: DailyReportPlatform, cfg
    ) -> tuple[str, object | None, object | None]:
        if platform != "pdd" or not cfg.daily_report_schedule_use_saved_preview:
            draft = generate_daily_report_draft(platform=platform)
            return draft.message, draft, None

        saved = load_wecom_daily_content()
        if has_saved_pdd_preview(saved):
            message = build_saved_pdd_daily_report_message(saved)
            logger.info("wecom daily report scheduled send uses saved preview for %s", saved.content_date)
            return message, None, saved

        logger.warning(
            "wecom daily report schedule_use_saved_preview enabled but no saved preview; fallback to generate"
        )
        draft = generate_daily_report_draft(platform=platform)
        return draft.message, draft, None

    def _send_daily_report(
        self,
        platform: DailyReportPlatform,
        cfg,
        *,
        trigger_kind: str = "manual",
        message: str = "",
    ) -> bool:
        draft = None
        saved_content = None
        content = str(message or "").strip()
        try:
            if not content:
                if trigger_kind == "scheduled":
                    content, draft, saved_content = self._resolve_scheduled_message(platform, cfg)
                else:
                    draft = generate_daily_report_draft(platform=platform)
                    content = draft.message
            send_markdown(content, cfg=cfg, for_daily_report=True)
            report_day = today_in_tz()
            if draft:
                report_day = date.fromisoformat(draft.report_date)
            elif saved_content and saved_content.content_date:
                report_day = date.fromisoformat(saved_content.content_date)
            window_start = None
            window_end = None
            if draft and draft.listing_window_start:
                try:
                    window_start = datetime.strptime(draft.listing_window_start, "%Y-%m-%d %H:%M")
                    window_end = datetime.strptime(draft.listing_window_end, "%Y-%m-%d %H:%M")
                except ValueError:
                    window_start, window_end = report_listing_window(reference_day=report_day)
            elif saved_content and saved_content.pdd.listing_window_start:
                try:
                    window_start = datetime.strptime(
                        saved_content.pdd.listing_window_start, "%Y-%m-%d %H:%M"
                    )
                    window_end = datetime.strptime(
                        saved_content.pdd.listing_window_end, "%Y-%m-%d %H:%M"
                    )
                except ValueError:
                    window_start, window_end = report_listing_window(reference_day=report_day)
            self._record_send(
                platform=platform,
                report_date=report_day,
                message=content,
                trigger_kind=trigger_kind,
                ok=True,
                window_start=window_start,
                window_end=window_end,
                cfg=cfg,
            )
            logger.info(
                "wecom daily report sent platform=%s commits=%s stores=%s webhook=%s",
                platform,
                draft.commit_count if draft else 0,
                len(draft.store_summaries) if draft else 0,
                resolve_daily_report_webhook_url(cfg)[:32],
            )
            return True
        except WecomAPIError as exc:
            report_day = today_in_tz()
            if draft:
                report_day = date.fromisoformat(draft.report_date)
            elif saved_content and saved_content.content_date:
                report_day = date.fromisoformat(saved_content.content_date)
            self._record_send(
                platform=platform,
                report_date=report_day,
                message=content,
                trigger_kind=trigger_kind,
                ok=False,
                errcode=int(exc.errcode or -1),
                errmsg=str(exc),
                cfg=cfg,
            )
            logger.exception("wecom daily report send failed platform=%s", platform)
            return False
        except Exception as exc:
            report_day = today_in_tz()
            if draft:
                report_day = date.fromisoformat(draft.report_date)
            elif saved_content and saved_content.content_date:
                report_day = date.fromisoformat(saved_content.content_date)
            self._record_send(
                platform=platform,
                report_date=report_day,
                message=content,
                trigger_kind=trigger_kind,
                ok=False,
                errmsg=str(exc),
                cfg=cfg,
            )
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
        if not daily_report_webhook_configured(cfg):
            raise RuntimeError("企业微信未配置或未启用日报 Webhook")
        custom = str(message or "").strip()
        ok = self._send_daily_report(
            platform,
            cfg,
            trigger_kind="manual",
            message=custom,
        )
        if ok and platform == "pdd":
            self._last_run_date = datetime.now(TZ).date()
        return ok

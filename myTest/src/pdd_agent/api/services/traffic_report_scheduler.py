"""投流昨日数据定时抓取调度（默认每天 00:01）。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pdd_agent.api.services.task_runner import create_traffic_run
from pdd_agent.api.services.task_queue import enqueue_traffic_report_scrape_task
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.session import is_database_available
from pdd_agent.domain.enums import RunStatus
from pdd_agent.integrations.feishu.config import load_feishu_config
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)
TZ = ZoneInfo("Asia/Shanghai")


class TrafficReportScheduler:
    def __init__(self, poll_seconds: float = 30.0) -> None:
        self._poll_seconds = poll_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_run_date: date | None = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        if not is_database_available():
            logger.warning("traffic report scheduler disabled: database unavailable")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("traffic report scheduler started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        logger.info("traffic report scheduler stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._maybe_enqueue_daily_jobs()
            except Exception:
                logger.exception("traffic report scheduler tick failed")
            await asyncio.sleep(self._poll_seconds)

    async def _maybe_enqueue_daily_jobs(self) -> None:
        cfg = load_feishu_config()
        marketing_cfg = cfg.pdd_marketing_log
        if not marketing_cfg.enabled or not marketing_cfg.traffic_report_enabled:
            return

        now = datetime.now(TZ)
        target = now.replace(
            hour=int(marketing_cfg.traffic_report_schedule_hour),
            minute=int(marketing_cfg.traffic_report_schedule_minute),
            second=0,
            microsecond=0,
        )
        if now < target:
            return
        if self._last_run_date == now.date():
            return

        settings = load_yaml_settings()
        allowed_ids = {
            str(aid).strip()
            for aid in (marketing_cfg.traffic_report_account_ids or ["store_A"])
            if str(aid).strip()
        }
        accounts = [
            acc
            for acc in settings.accounts
            if acc.enabled and acc.account_id in allowed_ids
        ]
        if not accounts:
            logger.warning(
                "traffic report scheduler skipped: no enabled accounts in %s",
                sorted(allowed_ids),
            )
            self._last_run_date = now.date()
            return

        store = TaskRunStore()
        scheduled_at = datetime.now()
        enqueued = 0
        for account in accounts:
            run_id = create_traffic_run(account.account_id)
            store.update_status(run_id, RunStatus.PENDING, "投流昨日数据抓取已加入队列")
            enqueue_traffic_report_scrape_task(
                run_id=run_id,
                account_id=account.account_id,
                scheduled_at=scheduled_at,
            )
            enqueued += 1
            logger.info(
                "traffic report scrape enqueued account=%s run_id=%s at=%s",
                account.account_id,
                run_id,
                now.isoformat(),
            )

        self._last_run_date = now.date()
        print(
            f"[scheduler] 投流昨日数据定时任务已入队：{enqueued} 家店铺（{', '.join(a.account_id for a in accounts)}），"
            f"触发时间={now.strftime('%Y-%m-%d %H:%M:%S')}",
            flush=True,
        )

    def trigger_now(self) -> int:
        """手动触发：立即为配置的店铺入队投流抓取任务。"""
        settings = load_yaml_settings()
        cfg = load_feishu_config()
        allowed_ids = {
            str(aid).strip()
            for aid in (cfg.pdd_marketing_log.traffic_report_account_ids or ["store_A"])
            if str(aid).strip()
        }
        accounts = [
            acc
            for acc in settings.accounts
            if acc.enabled and acc.account_id in allowed_ids
        ]
        store = TaskRunStore()
        scheduled_at = datetime.now()
        count = 0
        for account in accounts:
            run_id = create_traffic_run(account.account_id)
            store.update_status(run_id, RunStatus.PENDING, "投流昨日数据抓取已加入队列（手动触发）")
            enqueue_traffic_report_scrape_task(
                run_id=run_id,
                account_id=account.account_id,
                scheduled_at=scheduled_at,
            )
            count += 1
        return count

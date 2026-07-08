"""库存下架 — 定时间隔调度。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from pdd_agent.core.logging import get_logger
from pdd_agent.db.session import is_database_available
from pdd_agent.inventory_delist.account_resolver import resolve_enabled_account_ids
from pdd_agent.inventory_delist.config import load_inventory_delist_config
from pdd_agent.inventory_delist.job_store import get_last_scheduled_run_at, set_last_scheduled_run_at
from pdd_agent.inventory_delist.run_watcher import tick_inventory_delist_jobs

logger = get_logger(__name__)

_scheduler: "InventoryDelistScheduler | None" = None


class InventoryDelistScheduler:
    def __init__(self, poll_seconds: float = 30.0) -> None:
        self._poll_seconds = poll_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        if not is_database_available():
            logger.warning("inventory delist scheduler disabled: database unavailable")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("inventory delist scheduler started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        logger.info("inventory delist scheduler stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                cfg = load_inventory_delist_config()
                tick_inventory_delist_jobs(
                    delist_spec_code_search_enabled=bool(cfg.delist_spec_code_search_enabled),
                )
                await self._maybe_trigger_scheduled_run(cfg)
            except Exception:
                logger.exception("inventory delist scheduler tick failed")
            await asyncio.sleep(self._poll_seconds)

    async def _maybe_trigger_scheduled_run(self, cfg) -> None:
        if not cfg.enabled:
            return
        account_ids = self._resolve_account_ids(cfg.account_ids)
        if not account_ids:
            return

        now = datetime.now()
        last_text = get_last_scheduled_run_at()
        last_run: datetime | None = None
        if last_text:
            try:
                last_run = datetime.fromisoformat(last_text)
            except ValueError:
                last_run = None
        interval = timedelta(hours=float(cfg.interval_hours))
        if last_run and now - last_run < interval:
            return

        try:
            from pdd_agent.inventory_delist.service import trigger_inventory_delist_run

            result = await asyncio.to_thread(
                trigger_inventory_delist_run,
                account_ids=account_ids,
                execution_mode=cfg.execution_mode,
                delist_spec_code_search_enabled=bool(cfg.delist_spec_code_search_enabled),
                trigger="schedule",
            )
            set_last_scheduled_run_at(now.isoformat(timespec="seconds"))
            logger.info(
                "inventory delist scheduled run job_id=%s accounts=%s",
                result.get("job_id"),
                len(account_ids),
            )
        except Exception:
            logger.exception("inventory delist scheduled run failed")

    def _resolve_account_ids(self, configured_ids: list[str]) -> list[str]:
        resolved, _ = resolve_enabled_account_ids(configured_ids)
        return resolved


def get_inventory_delist_scheduler() -> InventoryDelistScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = InventoryDelistScheduler()
    return _scheduler

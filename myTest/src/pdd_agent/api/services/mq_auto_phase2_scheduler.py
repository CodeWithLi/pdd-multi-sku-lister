"""RabbitMQ 自动上架阶段二（活动/推广）定时调度。"""

from __future__ import annotations

import asyncio

from pdd_agent.api.services.pipeline_mq_auto_phase2 import tick_mq_auto_phase2
from pdd_agent.core.logging import get_logger
from pdd_agent.db.session import is_database_available

logger = get_logger(__name__)

_scheduler: "MqAutoPhase2Scheduler | None" = None


def get_mq_auto_phase2_scheduler() -> "MqAutoPhase2Scheduler":
    global _scheduler
    if _scheduler is None:
        _scheduler = MqAutoPhase2Scheduler()
    return _scheduler


class MqAutoPhase2Scheduler:
    def __init__(self, poll_seconds: float = 30.0) -> None:
        self._poll_seconds = poll_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        logger.info("mq auto phase2 scheduler started")
        while not self._stop.is_set():
            try:
                if is_database_available():
                    summary = await asyncio.to_thread(tick_mq_auto_phase2, limit=1)
                    if summary.get("started"):
                        logger.info(
                            "mq auto phase2 tick processed=%s started=%s",
                            summary.get("processed"),
                            summary.get("started"),
                        )
            except Exception:
                logger.exception("mq auto phase2 scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                continue
        logger.info("mq auto phase2 scheduler stopped")

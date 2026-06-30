"""店铺运营意图队列后台派发。"""

from __future__ import annotations

import asyncio

from pdd_agent.api.services.commerce_dispatch import reconcile_commerce_state
from pdd_agent.core.logging import get_logger
from pdd_agent.db.session import is_database_available

logger = get_logger(__name__)

_scheduler: "CommerceDispatchScheduler | None" = None


def get_commerce_dispatch_scheduler() -> "CommerceDispatchScheduler":
    global _scheduler
    if _scheduler is None:
        _scheduler = CommerceDispatchScheduler()
    return _scheduler


class CommerceDispatchScheduler:
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
        logger.info("commerce dispatch scheduler started")
        while not self._stop.is_set():
            try:
                if is_database_available():
                    summary = await asyncio.to_thread(reconcile_commerce_state, dispatch_limit=30)
                    if summary.get("dispatched_count"):
                        logger.info(
                            "commerce dispatch tick nudged=%s synced=%s dispatched=%s",
                            summary.get("nudged"),
                            summary.get("synced"),
                            summary.get("dispatched_count"),
                        )
            except Exception:
                logger.exception("commerce dispatch scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                continue
        logger.info("commerce dispatch scheduler stopped")

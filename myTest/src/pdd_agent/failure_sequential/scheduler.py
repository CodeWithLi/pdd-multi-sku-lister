"""失败日志分阶段流水线后台调度。"""

from __future__ import annotations

import asyncio
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.failure_sequential.orchestrator import is_batch_active, tick_once
from pdd_agent.integrations.feishu.config import load_feishu_config

logger = get_logger(__name__)

_scheduler: "FailureSequentialScheduler | None" = None


def get_failure_sequential_scheduler() -> "FailureSequentialScheduler":
    global _scheduler
    if _scheduler is None:
        _scheduler = FailureSequentialScheduler()
    return _scheduler


def is_failure_sequential_busy() -> bool:
    """有活跃批次时，整合链路轮询应暂停自动触发。"""
    try:
        cfg = load_feishu_config()
        watch = cfg.pdd_upload_log.failure_cycle_relist_watch
        if not watch.sequential_staged_enabled:
            return False
        return is_batch_active()
    except Exception:
        return False


class FailureSequentialScheduler:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_tick_at: str = ""
        self._last_error: str = ""
        self._last_summary: dict[str, Any] = {}

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_tick_at(self) -> str:
        return self._last_tick_at

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def last_summary(self) -> dict[str, Any]:
        return dict(self._last_summary)

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
        logger.info("failure sequential scheduler started")
        while not self._stop.is_set():
            try:
                cfg = load_feishu_config()
                watch = cfg.pdd_upload_log.failure_cycle_relist_watch
                if watch.enabled and watch.sequential_staged_enabled:
                    summary = await asyncio.to_thread(tick_once)
                    from pdd_agent.integrations.feishu.pdd_failure_log_watch import utc_now_iso

                    self._last_tick_at = utc_now_iso()
                    self._last_summary = summary
                    if not summary.get("ok"):
                        self._last_error = str(summary.get("error") or "")
                    elif summary.get("action") not in {"idle", "disabled", "no_candidates"}:
                        self._last_error = ""
                else:
                    self._last_summary = {"action": "disabled"}
            except Exception as exc:
                logger.exception("failure sequential scheduler loop error")
                self._last_error = str(exc)
            try:
                cfg = load_feishu_config()
                poll_seconds = int(cfg.pdd_upload_log.failure_cycle_relist_watch.poll_seconds)
            except Exception:
                poll_seconds = 60
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(10, poll_seconds))
            except asyncio.TimeoutError:
                continue
        logger.info("failure sequential scheduler stopped")

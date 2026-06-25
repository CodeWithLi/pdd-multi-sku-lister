"""平台跳过去重：定时从飞书失败日志同步编码到 Redis。"""

from __future__ import annotations

import asyncio
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.config import load_feishu_config, platform_skip_dedupe_enabled
from pdd_agent.integrations.feishu.platform_skip_dedupe_cache import sync_platform_skip_codes_from_feishu

logger = get_logger(__name__)


class PlatformSkipDedupeScheduler:
    """开启后每隔 N 秒从飞书失败日志刷新 Redis 跳过编码集合。"""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_sync_at: str = ""
        self._last_error: str = ""
        self._last_code_count: int = 0

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_sync_at(self) -> str:
        return self._last_sync_at

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def last_code_count(self) -> int:
        return self._last_code_count

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info("platform skip dedupe scheduler started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("platform skip dedupe scheduler stopped")

    async def sync_once(self) -> dict[str, Any]:
        result = await asyncio.to_thread(sync_platform_skip_codes_from_feishu)
        if result.get("ok"):
            meta = dict(result.get("meta") or {})
            self._last_sync_at = str(meta.get("updated_at") or "")
            self._last_code_count = int(meta.get("code_count") or 0)
            self._last_error = ""
        else:
            self._last_error = str(result.get("error") or "sync failed")
        return result

    async def _loop(self) -> None:
        while not self._stop.is_set():
            interval = 300
            try:
                cfg = load_feishu_config()
                interval = max(60, int(cfg.pipeline.platform_skip_dedupe_sync_seconds or 300))
                if platform_skip_dedupe_enabled(cfg):
                    await self.sync_once()
            except Exception:
                logger.exception("platform skip dedupe scheduler tick failed")
                self._last_error = "scheduler tick failed"
                interval = 300
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue


_scheduler: PlatformSkipDedupeScheduler | None = None


def get_platform_skip_dedupe_scheduler() -> PlatformSkipDedupeScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = PlatformSkipDedupeScheduler()
    return _scheduler

"""MinIO 上传事件 SSE 广播（供前端实时刷新）。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None
_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
_subscribers_lock = asyncio.Lock()


def bind_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


async def subscribe_minio_events():
    """SSE 订阅：yield dict 事件。"""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    async with _subscribers_lock:
        _subscribers.add(queue)
    try:
        while True:
            payload = await queue.get()
            yield payload
    finally:
        async with _subscribers_lock:
            _subscribers.discard(queue)


async def _publish_event(payload: dict[str, Any]) -> None:
    async with _subscribers_lock:
        targets = list(_subscribers)
    for queue in targets:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("minio sse subscriber queue full, dropping event")


def publish_minio_event(payload: dict[str, Any]) -> None:
    """线程安全：从 RabbitMQ 消费线程推送事件到 SSE 订阅者。"""
    loop = _main_loop
    if loop is None or not loop.is_running():
        logger.debug("minio event dropped (no event loop): %s", payload.get("kind"))
        return
    asyncio.run_coroutine_threadsafe(_publish_event(payload), loop)


def format_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

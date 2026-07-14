"""飞书回写异步调度 — 独立封装，避免阻塞 FastAPI 事件循环。

出问题时删除本文件，并在各 schedule_* 恢复内联 threading.Thread 即可。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

__all__ = ["schedule_feishu_push_in_background"]


def schedule_feishu_push_in_background(
    target: Callable[..., Any],
    *,
    thread_name: str,
    kwargs: dict[str, Any] | None = None,
) -> None:
    """在 daemon 后台线程执行飞书 push（成功/失败均异步，不阻塞页面）。"""
    thread = threading.Thread(
        target=target,
        kwargs=dict(kwargs or {}),
        name=thread_name,
        daemon=True,
    )
    thread.start()

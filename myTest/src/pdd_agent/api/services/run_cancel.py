"""运行中任务取消标记（供浏览器线程协作式中止）。"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_cancelled_run_ids: set[str] = set()


def request_cancel(run_id: str) -> None:
    rid = str(run_id or "").strip()
    if not rid:
        return
    with _lock:
        _cancelled_run_ids.add(rid)


def clear_cancel(run_id: str) -> None:
    rid = str(run_id or "").strip()
    if not rid:
        return
    with _lock:
        _cancelled_run_ids.discard(rid)


def is_cancelled(run_id: str) -> bool:
    rid = str(run_id or "").strip()
    if not rid:
        return False
    with _lock:
        return rid in _cancelled_run_ids

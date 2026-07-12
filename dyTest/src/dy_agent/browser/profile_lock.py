"""按店铺 Profile 互斥锁，避免并发操作同一浏览器数据目录。"""

from __future__ import annotations

import threading
from contextlib import contextmanager

from dy_agent.core.config import YamlSettings

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _get_lock(account_id: str) -> threading.Lock:
    with _guard:
        if account_id not in _locks:
            _locks[account_id] = threading.Lock()
        return _locks[account_id]


@contextmanager
def account_profile_lock(settings: YamlSettings, account_id: str, *, reason: str = ""):
    lock = _get_lock(account_id)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()

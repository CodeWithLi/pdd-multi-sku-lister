"""按店铺 Profile 互斥锁，避免并发操作同一浏览器数据目录。"""

from __future__ import annotations

import threading
from contextlib import contextmanager

from dy_agent.core.config import YamlSettings

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


class AccountProfileBusy(RuntimeError):
    """Profile 被其他任务占用。"""


def _get_lock(account_id: str) -> threading.Lock:
    with _guard:
        if account_id not in _locks:
            _locks[account_id] = threading.Lock()
        return _locks[account_id]


@contextmanager
def account_profile_lock(
    settings: YamlSettings,
    account_id: str,
    *,
    reason: str = "",
    wait_seconds: int = 300,
):
    lock = _get_lock(account_id)
    acquired = lock.acquire(timeout=max(0, wait_seconds) if wait_seconds > 0 else -1)
    if not acquired:
        raise AccountProfileBusy(f"店铺 {account_id} 浏览器 Profile 正被占用（{reason or 'busy'}）")
    try:
        yield
    finally:
        lock.release()

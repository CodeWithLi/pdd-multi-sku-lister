"""Per-account browser profile lock."""

from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pdd_agent.core.config import YamlSettings
from pdd_agent.db.repositories import acquire_account_lock, release_account_lock
from pdd_agent.db.session import is_database_available


class AccountProfileBusy(RuntimeError):
    pass


@contextmanager
def account_profile_lock(
    settings: YamlSettings,
    account_id: str,
    *,
    reason: str,
    wait_seconds: int = 10,
    ttl_seconds: int = 7200,
) -> Iterator[None]:
    owner = f"{os.getpid()}_{uuid.uuid4().hex[:10]}"
    if is_database_available():
        acquired = _acquire_db_lock(
            account_id=account_id,
            owner=owner,
            reason=reason,
            wait_seconds=wait_seconds,
            ttl_seconds=ttl_seconds,
        )
        if not acquired:
            raise AccountProfileBusy(f"[{account_id}] profile busy: another task is using this store")
        try:
            yield
        finally:
            release_account_lock(account_id=account_id, owner=owner)
        return

    lock_path = settings.paths.resolve("profiles_root") / account_id / "profile.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired_file = _acquire_file_lock(lock_path, owner, wait_seconds, ttl_seconds)
    if not acquired_file:
        raise AccountProfileBusy(f"[{account_id}] profile busy: {lock_path}")
    try:
        yield
    finally:
        try:
            if lock_path.read_text(encoding="utf-8").startswith(owner):
                lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _acquire_db_lock(
    *,
    account_id: str,
    owner: str,
    reason: str,
    wait_seconds: int,
    ttl_seconds: int,
) -> bool:
    deadline = time.time() + wait_seconds
    while True:
        if acquire_account_lock(
            account_id=account_id,
            owner=owner,
            reason=reason,
            ttl_seconds=ttl_seconds,
        ):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(1)


def _acquire_file_lock(lock_path: Path, owner: str, wait_seconds: int, ttl_seconds: int) -> bool:
    deadline = time.time() + wait_seconds
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"{owner}\n{time.time()}\n")
            return True
        except FileExistsError:
            if _file_lock_expired(lock_path, ttl_seconds):
                lock_path.unlink(missing_ok=True)
                continue
            if time.time() >= deadline:
                return False
            time.sleep(1)


def _file_lock_expired(lock_path: Path, ttl_seconds: int) -> bool:
    try:
        return time.time() - lock_path.stat().st_mtime > ttl_seconds
    except OSError:
        return True

"""Persistent task queue worker."""

from __future__ import annotations

import asyncio
from typing import Any

from pdd_agent.api.services.task_runner import execute_delist, execute_listing
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    claim_due_task,
    count_running_queue_tasks,
    enqueue_task,
    finish_queue_task,
    release_stale_account_locks,
    requeue_interrupted_tasks,
)
from pdd_agent.db.session import is_database_available
from pdd_agent.domain.enums import AgentKind, RunStatus
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)


class TaskQueueWorker:
    def __init__(self, poll_seconds: float = 2.0) -> None:
        self._poll_seconds = poll_seconds
        self._stop = asyncio.Event()
        self._main_task: asyncio.Task | None = None
        self._running: set[asyncio.Task] = set()
        self._task_handles: dict[str, tuple[asyncio.Task, str, str]] = {}

    def cancel_running(self, account_id: str = "") -> list[str]:
        """取消运行中的队列任务（标记 DB、中止 asyncio 任务、请求浏览器协作退出）。"""
        from pdd_agent.api.services.run_cancel import request_cancel
        from pdd_agent.db.repositories import cancel_running_tasks

        rows = cancel_running_tasks(account_id=account_id)
        run_ids: list[str] = []
        store = TaskRunStore()
        for item in rows:
            run_id = str(item.get("run_id") or "")
            if not run_id:
                continue
            run_ids.append(run_id)
            request_cancel(run_id)
            store.update_status(run_id, RunStatus.CANCELED, "canceled by user")

        for task_id, (task, _, acc) in list(self._task_handles.items()):
            if account_id and acc != account_id:
                continue
            if not task.done():
                task.cancel()

        return run_ids

    def start(self) -> None:
        if self._main_task and not self._main_task.done():
            return
        if not is_database_available():
            logger.warning("task queue disabled: database unavailable")
            return
        recovered = requeue_interrupted_tasks()
        if recovered:
            logger.warning("task queue recovered %s interrupted tasks", recovered)
        stale_locks = release_stale_account_locks()
        if stale_locks:
            logger.warning("task queue cleared %s stale account locks", stale_locks)
        self._main_task = asyncio.create_task(self._loop())
        logger.info("task queue worker started")

    async def stop(self) -> None:
        self._stop.set()
        if self._main_task:
            await self._main_task
        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)
        logger.info("task queue worker stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._dispatch_due_tasks()
            except Exception:
                logger.exception("task queue dispatch failed")
            await asyncio.sleep(self._poll_seconds)

    async def _dispatch_due_tasks(self) -> None:
        settings = load_yaml_settings()
        max_concurrent = max(1, min(5, settings.batch.max_concurrent_stores))

        while count_running_queue_tasks() < max_concurrent:
            row = claim_due_task(max_concurrent)
            if not row:
                break
            task = asyncio.create_task(self._run_task(row))
            self._running.add(task)
            self._task_handles[row.task_id] = (task, row.run_id, row.account_id or "")

            def _on_done(t: asyncio.Task, tid: str = row.task_id) -> None:
                self._running.discard(t)
                self._task_handles.pop(tid, None)

            task.add_done_callback(_on_done)

    async def _run_task(self, row) -> None:
        payload: dict[str, Any] = dict(row.payload or {})
        logger.info(
            "queue task started task_id=%s agent=%s account=%s run_id=%s",
            row.task_id,
            row.agent,
            row.account_id,
            row.run_id,
        )
        try:
            if row.agent == AgentKind.LISTING.value:
                result = await execute_listing(
                    run_id=row.run_id,
                    account_id=row.account_id,
                    product_codes=list(payload.get("product_codes") or []),
                    dry_run=bool(payload.get("dry_run", False)),
                    category_keyword=str(payload.get("category_keyword") or "玩偶"),
                    platform_listing_code=str(payload.get("platform_listing_code") or ""),
                    retry_item=dict(payload.get("retry_item") or {}),
                    slot_alignment_test=bool(payload.get("slot_alignment_test")),
                )
            elif row.agent == AgentKind.DELIST.value:
                result = await execute_delist(
                    run_id=row.run_id,
                    account_id=row.account_id,
                    dry_run=payload.get("dry_run"),
                    delist_params=dict(payload.get("delist_params") or {}),
                )
            else:
                raise ValueError(f"unsupported queued agent: {row.agent}")

            record = TaskRunStore().load(row.run_id)
            if record and record.status == RunStatus.CANCELED:
                finish_queue_task(row.task_id, success=False, error="canceled by user")
                return
            success = bool(record and record.status == RunStatus.SUCCESS)
            error = "" if success else str(result.get("error") or result.get("errors") or "")
            finish_queue_task(row.task_id, success=success, error=error)
        except asyncio.CancelledError:
            from pdd_agent.api.services.run_cancel import clear_cancel, request_cancel

            request_cancel(row.run_id)
            TaskRunStore().update_status(row.run_id, RunStatus.CANCELED, "canceled by user")
            finish_queue_task(row.task_id, success=False, error="canceled by user")
            clear_cancel(row.run_id)
            logger.info("queue task canceled task_id=%s run_id=%s", row.task_id, row.run_id)
            raise
        except Exception as exc:
            logger.exception("queue task failed task_id=%s", row.task_id)
            finish_queue_task(row.task_id, success=False, error=str(exc))


def enqueue_listing_task(
    *,
    run_id: str,
    account_id: str,
    product_codes: list[str],
    dry_run: bool,
    category_keyword: str,
    scheduled_at,
    platform_listing_code: str = "",
    retry_item: dict | None = None,
    slot_alignment_test: bool = False,
):
    return enqueue_task(
        agent=AgentKind.LISTING.value,
        run_id=run_id,
        account_id=account_id,
        payload={
            "product_codes": list(product_codes),
            "dry_run": dry_run,
            "category_keyword": category_keyword,
            "platform_listing_code": platform_listing_code,
            "retry_item": dict(retry_item or {}),
            "slot_alignment_test": bool(slot_alignment_test),
        },
        scheduled_at=scheduled_at,
    )


def enqueue_delist_task(
    *,
    run_id: str,
    account_id: str,
    dry_run: bool | None,
    delist_params: dict,
    scheduled_at,
):
    payload = {"delist_params": dict(delist_params)}
    if dry_run is not None:
        payload["dry_run"] = dry_run
    return enqueue_task(
        agent=AgentKind.DELIST.value,
        run_id=run_id,
        account_id=account_id,
        payload=payload,
        scheduled_at=scheduled_at,
    )

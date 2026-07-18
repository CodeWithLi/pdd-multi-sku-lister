"""Persistent task queue worker."""

from __future__ import annotations

import asyncio
from typing import Any

from pdd_agent.api.services.task_runner import (
    ensure_feishu_logged_for_terminal_run,
    execute_campaign_marketing_activity_register,
    execute_delist,
    execute_listing,
    execute_traffic_promotion_create,
    execute_traffic_promotion_report_scrape,
)
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


def _extract_queue_task_error(result: dict[str, Any]) -> str:
    if result.get("error"):
        return str(result["error"])
    errors = result.get("errors")
    if isinstance(errors, list):
        return "; ".join(str(item).strip() for item in errors if str(item).strip())
    return str(errors or "")


def _ensure_terminal_feishu_log(
    row,
    *,
    payload: dict[str, Any],
    result: dict[str, Any] | None,
    error: str,
    run_status: RunStatus,
) -> None:
    if run_status == RunStatus.SUCCESS:
        return
    try:
        ensure_feishu_logged_for_terminal_run(
            run_id=row.run_id,
            agent=row.agent,
            account_id=row.account_id,
            payload=payload,
            result=result if isinstance(result, dict) else {},
            error=error,
            run_status=run_status,
        )
    except Exception:
        logger.exception("ensure terminal feishu log failed run_id=%s", row.run_id)


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

    def cancel_run_ids(self, run_ids: list[str]) -> list[str]:
        """取消指定 run_id 的队列任务（排队中 + 运行中）。"""
        from pdd_agent.api.services.run_cancel import request_cancel
        from pdd_agent.db.repositories import cancel_queue_tasks_by_run_ids

        target = {str(run_id or "").strip() for run_id in run_ids if str(run_id or "").strip()}
        if not target:
            return []

        rows = cancel_queue_tasks_by_run_ids(list(target))
        store = TaskRunStore()
        canceled: list[str] = []
        for item in rows:
            run_id = str(item.get("run_id") or "")
            if not run_id:
                continue
            canceled.append(run_id)
            request_cancel(run_id)
            store.update_status(run_id, RunStatus.CANCELED, "canceled by user")

        for task_id, (task, run_id, _) in list(self._task_handles.items()):
            if run_id in target and not task.done():
                task.cancel()

        return list(dict.fromkeys(canceled))

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
        pipeline_id = str(payload.get("pipeline_id") or "").strip()
        logger.info(
            "queue task started task_id=%s agent=%s account=%s run_id=%s",
            row.task_id,
            row.agent,
            row.account_id,
            row.run_id,
        )
        result: dict[str, Any] = {}
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
                    spec_fill_verify_test=bool(payload.get("spec_fill_verify_test")),
                    primary_style_first_test=bool(payload.get("primary_style_first_test")),
                    paren_size_as_product_type=bool(payload.get("paren_size_as_product_type")),
                    category_next_burst_demo=bool(payload.get("category_next_burst_demo", True)),
                    material_source=str(payload.get("material_source") or ""),
                    use_minio_cache_only=bool(payload.get("use_minio_cache_only")),
                    pipeline_id=str(payload.get("pipeline_id") or ""),
                    pipeline_late_retry=bool(payload.get("pipeline_late_retry")),
                )
            elif row.agent == AgentKind.DELIST.value:
                result = await execute_delist(
                    run_id=row.run_id,
                    account_id=row.account_id,
                    dry_run=payload.get("dry_run"),
                    delist_params=dict(payload.get("delist_params") or {}),
                )
            elif row.agent == AgentKind.CAMPAIGN.value:
                campaign_type = str(payload.get("campaign_type") or "marketing_activity_register")
                if campaign_type == "limited_time_setup":
                    from pdd_agent.api.services.task_runner import execute_campaign_limited_time_setup

                    result = await execute_campaign_limited_time_setup(
                        run_id=row.run_id,
                        account_id=row.account_id,
                        pdd_product_ids=list(payload.get("pdd_product_ids") or []),
                        published_mapping_ids=list(payload.get("published_mapping_ids") or []),
                    )
                else:
                    if pipeline_id:
                        from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
                            maybe_defer_activity_task_execution,
                        )
                        from pdd_agent.db.repositories import get_integrated_pipeline

                        pipe_row = get_integrated_pipeline(pipeline_id)
                        if pipe_row and maybe_defer_activity_task_execution(
                            pipe_row,
                            task_id=row.task_id,
                            run_id=row.run_id,
                        ):
                            logger.info(
                                "queue task deferred task_id=%s run_id=%s pipeline_id=%s",
                                row.task_id,
                                row.run_id,
                                pipeline_id,
                            )
                            return

                    from pdd_agent.api.services.pipeline_late_retry_policy import (
                        resolve_campaign_pdd_ids_at_execution,
                    )

                    result = await execute_campaign_marketing_activity_register(
                        run_id=row.run_id,
                        account_id=row.account_id,
                        activity_id=str(payload.get("activity_id") or ""),
                        pdd_product_ids=resolve_campaign_pdd_ids_at_execution(
                            pipeline_id=str(payload.get("pipeline_id") or ""),
                            payload_pdd_ids=list(payload.get("pdd_product_ids") or []),
                        ),
                    )
            elif row.agent == AgentKind.TRAFFIC.value:
                traffic_type = str(payload.get("traffic_type") or "promotion_create")
                if traffic_type == "promotion_report_scrape":
                    result = await execute_traffic_promotion_report_scrape(
                        run_id=row.run_id,
                        account_id=row.account_id,
                    )
                else:
                    result = await execute_traffic_promotion_create(
                        run_id=row.run_id,
                        account_id=row.account_id,
                        pdd_product_ids=list(payload.get("pdd_product_ids") or []),
                        published_mapping_ids=list(payload.get("published_mapping_ids") or []),
                    )
            else:
                raise ValueError(f"unsupported queued agent: {row.agent}")

            record = TaskRunStore().load(row.run_id)
            if record and record.status == RunStatus.CANCELED:
                _ensure_terminal_feishu_log(
                    row,
                    payload=payload,
                    result=result if isinstance(result, dict) else {},
                    error="canceled by user",
                    run_status=RunStatus.CANCELED,
                )
                finish_queue_task(row.task_id, success=False, error="canceled by user")
                if pipeline_id:
                    from pdd_agent.api.services.pipeline_service import on_queue_task_finished

                    on_queue_task_finished(
                        agent=row.agent,
                        pipeline_id=pipeline_id,
                        run_id=row.run_id,
                        success=False,
                        result=result if isinstance(result, dict) else {},
                        error="canceled by user",
                    )
                return
            success = bool(record and record.status == RunStatus.SUCCESS)
            error = "" if success else _extract_queue_task_error(result)
            finish_queue_task(row.task_id, success=success, error=error)
            if pipeline_id:
                from pdd_agent.api.services.pipeline_service import on_queue_task_finished

                on_queue_task_finished(
                    agent=row.agent,
                    pipeline_id=pipeline_id,
                    run_id=row.run_id,
                    success=success,
                    result=result if isinstance(result, dict) else {},
                    error=error,
                )
        except asyncio.CancelledError:
            from pdd_agent.api.services.run_cancel import clear_cancel, request_cancel

            request_cancel(row.run_id)
            TaskRunStore().update_status(row.run_id, RunStatus.CANCELED, "canceled by user")
            _ensure_terminal_feishu_log(
                row,
                payload=payload,
                result={"error": "canceled by user"},
                error="canceled by user",
                run_status=RunStatus.CANCELED,
            )
            finish_queue_task(row.task_id, success=False, error="canceled by user")
            clear_cancel(row.run_id)
            if pipeline_id:
                try:
                    from pdd_agent.api.services.pipeline_issue_report_service import ingest_orchestration_issue
                    from pdd_agent.db.repositories import get_integrated_pipeline

                    ingest_orchestration_issue(
                        pipeline_row=get_integrated_pipeline(pipeline_id),
                        pipeline_id=pipeline_id,
                        chain_step="task_canceled",
                        reason_code="task_canceled",
                        message=f"整合链路子任务被取消（{row.agent}）",
                        severity="warning",
                        run_id=row.run_id,
                        context={"agent": row.agent},
                        source_location="task_queue._run_task",
                    )
                except Exception:
                    logger.warning("pipeline issue ingest failed pipeline_id=%s", pipeline_id, exc_info=True)
            logger.info("queue task canceled task_id=%s run_id=%s", row.task_id, row.run_id)
            raise
        except Exception as exc:
            logger.exception("queue task failed task_id=%s", row.task_id)
            _ensure_terminal_feishu_log(
                row,
                payload=payload,
                result={"error": str(exc)},
                error=str(exc),
                run_status=RunStatus.FAILED,
            )
            finish_queue_task(row.task_id, success=False, error=str(exc))
            if pipeline_id:
                from pdd_agent.api.services.pipeline_service import on_queue_task_finished

                on_queue_task_finished(
                    agent=row.agent,
                    pipeline_id=pipeline_id,
                    run_id=row.run_id,
                    success=False,
                    result={"error": str(exc)},
                    error=str(exc),
                )


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
    spec_fill_verify_test: bool = False,
    primary_style_first_test: bool = False,
    paren_size_as_product_type: bool = False,
    pipeline_id: str = "",
    material_source: str = "",
    use_minio_cache_only: bool = False,
):
    payload = {
        "product_codes": list(product_codes),
        "dry_run": dry_run,
        "category_keyword": category_keyword,
        "platform_listing_code": platform_listing_code,
        "retry_item": dict(retry_item or {}),
        "slot_alignment_test": bool(slot_alignment_test),
        "spec_fill_verify_test": bool(spec_fill_verify_test),
        "primary_style_first_test": bool(primary_style_first_test),
        "paren_size_as_product_type": bool(paren_size_as_product_type),
        "material_source": str(material_source or ""),
        "use_minio_cache_only": bool(use_minio_cache_only),
    }
    if pipeline_id:
        payload["pipeline_id"] = pipeline_id
    return enqueue_task(
        agent=AgentKind.LISTING.value,
        run_id=run_id,
        account_id=account_id,
        payload=payload,
        scheduled_at=scheduled_at,
    )


def enqueue_campaign_pipeline_task(
    *,
    run_id: str,
    account_id: str,
    activity_id: str,
    pdd_product_ids: list[str],
    scheduled_at,
    pipeline_id: str,
):
    return enqueue_task(
        agent=AgentKind.CAMPAIGN.value,
        run_id=run_id,
        account_id=account_id,
        payload={
            "pipeline_id": pipeline_id,
            "campaign_type": "marketing_activity_register",
            "activity_id": activity_id,
            "pdd_product_ids": list(pdd_product_ids),
        },
        scheduled_at=scheduled_at,
    )


def enqueue_traffic_pipeline_task(
    *,
    run_id: str,
    account_id: str,
    pdd_product_ids: list[str],
    published_mapping_ids: list[str],
    scheduled_at,
    pipeline_id: str,
):
    return enqueue_task(
        agent=AgentKind.TRAFFIC.value,
        run_id=run_id,
        account_id=account_id,
        payload={
            "pipeline_id": pipeline_id,
            "traffic_type": "promotion_create",
            "pdd_product_ids": list(pdd_product_ids),
            "published_mapping_ids": list(published_mapping_ids),
        },
        scheduled_at=scheduled_at,
    )


def enqueue_traffic_report_scrape_task(
    *,
    run_id: str,
    account_id: str,
    scheduled_at,
):
    return enqueue_task(
        agent=AgentKind.TRAFFIC.value,
        run_id=run_id,
        account_id=account_id,
        payload={"traffic_type": "promotion_report_scrape"},
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

"""失败日志循环上架候选轮询调度。"""

from __future__ import annotations

import asyncio
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.api.services.cycle_relist_audit_service import (
    record_cycle_relist_action,
    record_cycle_relist_poll,
)
from pdd_agent.db.repositories import list_integrated_pipelines
from pdd_agent.integrations.feishu.config import load_feishu_config
from pdd_agent.integrations.feishu.pdd_failure_log_watch import (
    list_cycle_relist_candidates,
    utc_now_iso,
)
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim import (
    get_cycle_relist_claim,
    try_claim_cycle_relist,
)
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger import (
    process_failure_cycle_relist_candidate,
)

logger = get_logger(__name__)
_TERMINAL_PIPELINE_STATUSES = {"completed", "failed", "canceled"}
_STALE_BLOCKER_HOURS = 6


def _pipeline_age_hours(row) -> float:
    updated = getattr(row, "updated_at", None)
    if not updated:
        return 9999.0
    from datetime import datetime

    return max(0.0, (datetime.now() - updated).total_seconds() / 3600.0)


class FailureCycleRelistWatchScheduler:
    """定时拉取飞书失败日志，发现新符合条件的候选记录。"""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_poll_at: str = ""
        self._last_error: str = ""
        self._candidate_total: int = 0
        self._new_items: list[dict[str, Any]] = []
        self._all_items: list[dict[str, Any]] = []
        self._last_claims: list[dict[str, Any]] = []
        self._last_pipeline_triggers: list[dict[str, Any]] = []
        self._was_candidate: dict[str, bool] = {}
        self._primed: bool = False
        self._record_actions: dict[str, dict[str, Any]] = {}
        self._recent_actions: list[dict[str, Any]] = []
        self._last_poll_log_id: str = ""

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_poll_at(self) -> str:
        return self._last_poll_at

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def candidate_total(self) -> int:
        return self._candidate_total

    @property
    def new_items(self) -> list[dict[str, Any]]:
        return list(self._new_items)

    @property
    def all_items(self) -> list[dict[str, Any]]:
        return list(self._all_items)

    @property
    def last_claims(self) -> list[dict[str, Any]]:
        return list(self._last_claims)

    @property
    def last_pipeline_triggers(self) -> list[dict[str, Any]]:
        return list(self._last_pipeline_triggers)

    @property
    def recent_actions(self) -> list[dict[str, Any]]:
        return list(self._recent_actions)

    @property
    def record_actions(self) -> dict[str, dict[str, Any]]:
        return dict(self._record_actions)

    def reset_tracking(self) -> None:
        self._was_candidate.clear()
        self._primed = False
        self._new_items = []
        self._last_claims = []
        self._last_pipeline_triggers = []
        self._record_actions.clear()
        self._recent_actions.clear()

    def record_action(
        self,
        *,
        record_id: str,
        merchant_code: str = "",
        status: str,
        message: str,
        pipeline_id: str = "",
        account_name: str = "",
        account_id: str = "",
        failure_reason: str = "",
        report_platform: str = "",
        trigger_source: str = "auto_watch",
        candidate: dict[str, Any] | None = None,
    ) -> None:
        rid = str(record_id or "").strip()
        if not rid:
            return
        item = candidate or {}
        merchant_code = str(merchant_code or item.get("merchant_code") or "")
        account_name = str(account_name or item.get("account_name") or "")
        account_id = str(account_id or item.get("account_id") or "")
        failure_reason = str(failure_reason or item.get("failure_reason") or "")
        report_platform = str(report_platform or item.get("report_platform") or "")
        action_at = utc_now_iso()
        status_text = str(status or "")
        message_text = str(message or "")
        prior = self._record_actions.get(rid) or {}
        if (
            prior.get("status") == status_text
            and prior.get("message") == message_text
            and prior.get("pipeline_id") == str(pipeline_id or "")
        ):
            return
        entry = {
            "at": action_at,
            "record_id": rid,
            "merchant_code": merchant_code,
            "account_name": account_name,
            "failure_reason": failure_reason,
            "status": status_text,
            "message": message_text,
            "pipeline_id": str(pipeline_id or ""),
            "trigger_source": str(trigger_source or "auto_watch"),
        }
        self._record_actions[rid] = entry
        self._recent_actions.insert(0, entry)
        self._recent_actions = self._recent_actions[:50]
        record_cycle_relist_action(
            record_id=rid,
            merchant_code=merchant_code,
            account_name=account_name,
            account_id=account_id,
            failure_reason=failure_reason,
            report_platform=report_platform,
            status=str(status or ""),
            message=str(message or ""),
            pipeline_id=str(pipeline_id or ""),
            trigger_source=str(trigger_source or "auto_watch"),
            poll_log_id=self._last_poll_log_id,
        )

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info("failure cycle relist watch scheduler started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        logger.info("failure cycle relist watch scheduler stopped")

    async def poll_once(self, *, force: bool = False) -> dict[str, Any]:
        return await asyncio.to_thread(self.poll_sync, force=force)

    def poll_sync(self, *, force: bool = False) -> dict[str, Any]:
        return self._poll_sync(force)

    def _poll_sync(self, force: bool = False) -> dict[str, Any]:
        cfg = load_feishu_config()
        watch = cfg.pdd_upload_log.failure_cycle_relist_watch
        if not watch.enabled and not force:
            return {
                "ok": True,
                "skipped": True,
                "reason": "watch_disabled",
                "new_items": [],
                "total": 0,
            }

        result = list_cycle_relist_candidates(cfg, watch=watch)
        self._last_poll_at = utc_now_iso()
        if not result.get("ok"):
            self._last_error = str(result.get("error") or "poll failed")
            return {
                "ok": False,
                "error": self._last_error,
                "new_items": [],
                "total": 0,
            }

        self._last_error = ""
        items = list(result.get("items") or [])
        self._all_items = items
        self._candidate_total = len(items)
        self._last_poll_log_id = ""

        for item in items:
            rid = str(item.get("record_id") or "")
            if not rid or get_cycle_relist_claim(rid):
                continue
            prior = self._record_actions.get(rid) or {}
            if prior.get("status") == "started" and str(prior.get("pipeline_id") or "").strip():
                continue
            if self._was_candidate.get(rid):
                self._was_candidate[rid] = False
                logger.info(
                    "cycle relist watch reset candidate for retry record_id=%s merchant_code=%s",
                    rid,
                    item.get("merchant_code"),
                )

        new_items: list[dict[str, Any]] = []
        primed_items: list[dict[str, Any]] = []
        if not self._primed and watch.ignore_existing_on_start:
            primed_count = 0
            for item in items:
                rid = str(item.get("record_id") or "")
                if rid:
                    self._was_candidate[rid] = True
                    primed_count += 1
                    primed_items.append(item)
            if primed_count:
                logger.info(
                    "failure cycle relist watch primed %s existing candidate(s)",
                    primed_count,
                )
            self._primed = True
        else:
            for item in items:
                rid = str(item.get("record_id") or "")
                if not rid:
                    continue
                if not self._was_candidate.get(rid):
                    new_items.append(item)
                    self._was_candidate[rid] = True
            self._primed = True

        for rid, was in list(self._was_candidate.items()):
            if rid not in {str(x.get("record_id") or "") for x in items}:
                self._was_candidate[rid] = False

        self._new_items = new_items
        for item in new_items:
            logger.info(
                "cycle relist watch new candidate record_id=%s merchant_code=%s source_pipeline_id=%s",
                item.get("record_id"),
                item.get("merchant_code"),
                item.get("source_pipeline_id") or "-",
            )
        poll_log_id = record_cycle_relist_poll(
            candidate_total=len(items),
            new_count=len(new_items),
            fetch_mode=str(result.get("fetch_mode") or ""),
            fetch_page_size=int(result.get("fetch_page_size") or 0),
            table_id=str(result.get("table_id") or ""),
            table_name=str(result.get("table_name") or ""),
            candidates=items,
            new_candidates=new_items,
        )
        self._last_poll_log_id = poll_log_id
        for item in primed_items:
            rid = str(item.get("record_id") or "")
            if not rid:
                continue
            self.record_action(
                record_id=rid,
                status="skipped",
                message="启动前已存在的候选，未自动处理（保存配置后会重新识别新变化）",
                trigger_source="prime_skip",
                candidate=item,
            )
        claims: list[dict[str, Any]] = []
        pipeline_triggers: list[dict[str, Any]] = []
        auto_process = bool(
            watch.enabled
            and watch.trigger_pipeline_on_discover
            and not watch.sequential_staged_enabled
        )
        try:
            from pdd_agent.failure_sequential.scheduler import is_failure_sequential_busy

            if is_failure_sequential_busy():
                auto_process = False
        except Exception:
            pass
        active_cycle_relist_pipeline_id = ""
        if auto_process:
            active_cycle_relist_pipeline_id = self._find_active_cycle_relist_pipeline_id()
        if new_items and (auto_process or watch.claim_on_discover):
            started_in_this_poll = False
            for item in new_items:
                rid = str(item.get("record_id") or "")
                merchant_code = str(item.get("merchant_code") or "")
                account_name = str(item.get("account_name") or "")
                account_id = str(item.get("account_id") or "")
                if auto_process:
                    # 严格串行：已有循环链路在跑时，本轮不再启动新链路。
                    if active_cycle_relist_pipeline_id:
                        logger.info(
                            "cycle relist auto trigger paused by active pipeline=%s record_id=%s",
                            active_cycle_relist_pipeline_id,
                            rid,
                        )
                        self.record_action(
                            record_id=rid,
                            status="waiting",
                            message=f"等待中：上一条循环链路仍在执行（{active_cycle_relist_pipeline_id}）",
                            candidate=item,
                        )
                        continue
                    # 同一轮仅允许启动 1 条，避免批量并发占满店铺/浏览器。
                    if started_in_this_poll:
                        self.record_action(
                            record_id=rid,
                            status="waiting",
                            message="等待中：本轮已有任务启动，下一轮继续",
                            candidate=item,
                        )
                        continue
                    outcome = process_failure_cycle_relist_candidate(
                        item,
                        config=cfg,
                        watch=watch,
                    )
                    pipeline_triggers.append(outcome)
                    if outcome.get("claim"):
                        claims.append(dict(outcome["claim"]))
                    resolved_account = str(outcome.get("account_id") or account_id or "").strip()
                    store_hint = account_name or resolved_account or "未知店铺"
                    if outcome.get("ok") and outcome.get("pipeline_id"):
                        started_in_this_poll = True
                        active_cycle_relist_pipeline_id = str(outcome.get("pipeline_id") or "")
                        self.record_action(
                            record_id=rid,
                            status="started",
                            message=f"已占用并启动整合链路（店铺：{store_hint}）",
                            pipeline_id=str(outcome.get("pipeline_id") or ""),
                            account_id=resolved_account,
                            candidate=item,
                        )
                    elif outcome.get("skipped"):
                        reason = str(outcome.get("reason") or "")
                        msg = {
                            "already_claimed": "Redis 已占用，可能正在处理或已处理过",
                            "report_platform_filtered": "报错平台不在自动处理范围内",
                            "already_on_sale": "商品编码在拼多多在售列表已存在，视为已完成，跳过重跑",
                        }.get(reason, f"已跳过：{reason or '未知原因'}")
                        self.record_action(
                            record_id=rid,
                            status="skipped",
                            message=msg,
                            candidate=item,
                        )
                    else:
                        err = str(outcome.get("error") or "自动跑链路失败")
                        self.record_action(
                            record_id=rid,
                            status="failed",
                            message=err,
                            candidate=item,
                        )
                        logger.warning(
                            "cycle relist pipeline trigger failed record_id=%s error=%s",
                            rid,
                            err,
                        )
                    continue

                if watch.claim_on_discover:
                    claim_result = try_claim_cycle_relist(
                        str(item.get("record_id") or ""),
                        merchant_code=str(item.get("merchant_code") or ""),
                        account_name=str(item.get("account_name") or ""),
                        account_id=str(item.get("account_id") or ""),
                        watch=watch,
                    )
                    claim_dict = claim_result.to_dict()
                    claims.append(claim_dict)
                    if not claim_result.claimed and claim_result.reason == "redis_locked":
                        logger.info(
                            "cycle relist claim skipped (locked) record_id=%s",
                            item.get("record_id"),
                        )
                    elif not claim_result.ok:
                        logger.warning(
                            "cycle relist claim failed record_id=%s error=%s",
                            item.get("record_id"),
                            claim_result.error,
                        )
        self._last_claims = claims
        self._last_pipeline_triggers = pipeline_triggers

        if new_items:
            logger.info(
                "failure cycle relist watch found %s new candidate(s): %s",
                len(new_items),
                ", ".join(str(x.get("merchant_code") or x.get("record_id")) for x in new_items[:5]),
            )
        return {
            "ok": True,
            "polled_at": self._last_poll_at,
            "total": self._candidate_total,
            "new_items": new_items,
            "new_count": len(new_items),
            "claims": claims,
            "pipeline_triggers": pipeline_triggers,
        }

    def get_blocker_info(self) -> dict[str, Any]:
        """返回当前阻塞自动循环上架的整合链路信息。"""
        pid, row, stale = self._resolve_blocker_pipeline(include_stale=True)
        if not pid or not row:
            return {
                "pipeline_id": "",
                "status": "",
                "stale": False,
                "age_hours": 0.0,
                "updated_at": "",
                "blocking": False,
            }
        updated = ""
        if getattr(row, "updated_at", None):
            updated = row.updated_at.isoformat(timespec="seconds")
        blocking = bool(pid) and not stale
        return {
            "pipeline_id": pid,
            "status": str(getattr(row, "status", "") or ""),
            "stale": stale,
            "age_hours": round(_pipeline_age_hours(row), 2),
            "updated_at": updated,
            "blocking": blocking,
        }

    def dismiss_blocker(self, *, pipeline_id: str = "") -> dict[str, Any]:
        """手动解除阻塞：终止僵尸链路，将等待记录标为失败并允许下一轮重试。"""
        pid, row, stale = self._resolve_blocker_pipeline(
            pipeline_id=pipeline_id,
            include_stale=True,
        )
        if not pid:
            return {"ok": True, "pipeline_id": "", "dismissed_records": 0, "message": "当前无阻塞链路"}
        err_msg = "手动解除阻塞（僵尸链路已终止，可重新处理）"
        try:
            from pdd_agent.api.services.pipeline_service import cancel_integrated_pipeline

            if row and str(row.status or "").lower() not in _TERMINAL_PIPELINE_STATUSES:
                cancel_integrated_pipeline(pid)
            else:
                from pdd_agent.db.repositories import update_integrated_pipeline

                update_integrated_pipeline(
                    pid,
                    status="failed",
                    current_step="failed",
                    error=err_msg,
                )
        except Exception as exc:
            logger.warning("dismiss blocker cancel pipeline failed pipeline=%s error=%s", pid, exc)
            try:
                from pdd_agent.db.repositories import update_integrated_pipeline

                update_integrated_pipeline(
                    pid,
                    status="failed",
                    current_step="failed",
                    error=err_msg,
                )
            except Exception:
                logger.exception("dismiss blocker force-fail pipeline failed pipeline=%s", pid)

        dismissed = self._mark_waiting_records_dismissed(pid, err_msg)
        logger.info(
            "cycle relist blocker dismissed pipeline=%s stale=%s dismissed_records=%s",
            pid,
            stale,
            dismissed,
        )
        return {
            "ok": True,
            "pipeline_id": pid,
            "dismissed_records": dismissed,
            "stale": stale,
            "message": err_msg,
        }

    def _mark_waiting_records_dismissed(self, pipeline_id: str, message: str) -> int:
        pid = str(pipeline_id or "").strip()
        if not pid:
            return 0
        seen: set[str] = set()
        targets: list[dict[str, Any]] = []

        for rid, action in list(self._record_actions.items()):
            if action.get("status") != "waiting":
                continue
            if pid not in str(action.get("message") or "") and action.get("pipeline_id") != pid:
                continue
            if rid in seen:
                continue
            seen.add(rid)
            targets.append({"record_id": rid, **action})

        for item in self._all_items:
            rid = str(item.get("record_id") or "").strip()
            if not rid or rid in seen:
                continue
            action = self._record_actions.get(rid) or {}
            if action.get("status") == "waiting":
                seen.add(rid)
                targets.append({"record_id": rid, **action, **item})

        try:
            from pdd_agent.db.repositories import list_failure_cycle_relist_waiting_for_pipeline

            for row in list_failure_cycle_relist_waiting_for_pipeline(pipeline_id=pid, limit=300):
                rid = str(row.feishu_record_id or "").strip()
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                targets.append(
                    {
                        "record_id": rid,
                        "merchant_code": row.merchant_code,
                        "account_name": row.account_name,
                        "failure_reason": row.failure_reason,
                    }
                )
        except Exception:
            logger.exception("list waiting actions for dismiss failed pipeline=%s", pid)

        for target in targets:
            rid = str(target.get("record_id") or "").strip()
            if not rid:
                continue
            self._was_candidate[rid] = False
            self.record_action(
                record_id=rid,
                merchant_code=str(target.get("merchant_code") or ""),
                account_name=str(target.get("account_name") or ""),
                failure_reason=str(target.get("failure_reason") or ""),
                status="failed",
                message=message,
                pipeline_id=pid,
                trigger_source="manual_dismiss",
            )
        return len(targets)

    def _resolve_blocker_pipeline(
        self,
        *,
        pipeline_id: str = "",
        include_stale: bool = False,
    ) -> tuple[str, Any, bool]:
        pid = str(pipeline_id or "").strip()
        row = None
        if pid:
            try:
                from pdd_agent.db.repositories import get_integrated_pipeline

                row = get_integrated_pipeline(pid)
            except Exception:
                row = None
            if row:
                status = str(row.status or "").strip().lower()
                if status in _TERMINAL_PIPELINE_STATUSES:
                    return "", None, False
                stale = _pipeline_age_hours(row) >= _STALE_BLOCKER_HOURS
                if stale and not include_stale:
                    return "", None, True
                return pid, row, stale
            return pid, None, False

        pid = self._find_active_cycle_relist_pipeline_id(include_stale=include_stale)
        if not pid:
            return "", None, False
        try:
            from pdd_agent.db.repositories import get_integrated_pipeline

            row = get_integrated_pipeline(pid)
        except Exception:
            row = None
        stale = bool(row and _pipeline_age_hours(row) >= _STALE_BLOCKER_HOURS)
        return pid, row, stale

    def _find_active_cycle_relist_pipeline_id(self, *, include_stale: bool = False) -> str:
        """查找仍在执行中的失败日志循环链路 pipeline_id。"""
        try:
            rows = list_integrated_pipelines(limit=200, offset=0)
        except Exception:
            logger.exception("list integrated pipelines failed")
            return ""
        for row in rows:
            status = str(getattr(row, "status", "") or "").strip().lower()
            if not status or status in _TERMINAL_PIPELINE_STATUSES:
                continue
            meta = getattr(row, "meta", None)
            meta_dict = meta if isinstance(meta, dict) else {}
            source = str(meta_dict.get("cycle_relist_source") or "").strip().lower()
            if source != "failure_log_watch":
                continue
            pid = str(getattr(row, "pipeline_id", "") or "").strip()
            if not pid:
                continue
            if not include_stale and _pipeline_age_hours(row) >= _STALE_BLOCKER_HOURS:
                logger.info(
                    "ignore stale cycle relist blocker pipeline=%s age_hours=%.1f",
                    pid,
                    _pipeline_age_hours(row),
                )
                continue
            return pid
        return ""

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                cfg = load_feishu_config()
                watch = cfg.pdd_upload_log.failure_cycle_relist_watch
                if watch.enabled:
                    await self.poll_once()
                interval = max(10, int(watch.poll_seconds or 60))
            except Exception:
                logger.exception("failure cycle relist watch tick failed")
                interval = 60
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue


_scheduler: FailureCycleRelistWatchScheduler | None = None


def get_failure_cycle_relist_watch_scheduler() -> FailureCycleRelistWatchScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = FailureCycleRelistWatchScheduler()
    return _scheduler

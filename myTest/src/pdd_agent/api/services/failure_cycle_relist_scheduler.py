"""失败日志循环上架候选轮询调度。"""

from __future__ import annotations

import asyncio
from typing import Any

from pdd_agent.core.logging import get_logger
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

    def _record_action(
        self,
        *,
        record_id: str,
        merchant_code: str = "",
        status: str,
        message: str,
        pipeline_id: str = "",
    ) -> None:
        rid = str(record_id or "").strip()
        if not rid:
            return
        entry = {
            "at": utc_now_iso(),
            "record_id": rid,
            "merchant_code": str(merchant_code or ""),
            "status": str(status or ""),
            "message": str(message or ""),
            "pipeline_id": str(pipeline_id or ""),
        }
        self._record_actions[rid] = entry
        self._recent_actions.insert(0, entry)
        self._recent_actions = self._recent_actions[:50]

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
        if not self._primed and watch.ignore_existing_on_start:
            primed_count = 0
            for item in items:
                rid = str(item.get("record_id") or "")
                if rid:
                    self._was_candidate[rid] = True
                    primed_count += 1
                    self._record_action(
                        record_id=rid,
                        merchant_code=str(item.get("merchant_code") or ""),
                        status="skipped",
                        message="启动前已存在的候选，未自动处理（保存配置后会重新识别新变化）",
                    )
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
        claims: list[dict[str, Any]] = []
        pipeline_triggers: list[dict[str, Any]] = []
        auto_process = bool(watch.enabled and watch.trigger_pipeline_on_discover)
        if new_items and (auto_process or watch.claim_on_discover):
            for item in new_items:
                rid = str(item.get("record_id") or "")
                merchant_code = str(item.get("merchant_code") or "")
                account_name = str(item.get("account_name") or "")
                account_id = str(item.get("account_id") or "")
                if auto_process:
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
                        self._record_action(
                            record_id=rid,
                            merchant_code=merchant_code,
                            status="started",
                            message=f"已占用并启动整合链路（店铺：{store_hint}）",
                            pipeline_id=str(outcome.get("pipeline_id") or ""),
                        )
                    elif outcome.get("skipped"):
                        reason = str(outcome.get("reason") or "")
                        msg = {
                            "already_claimed": "Redis 已占用，可能正在处理或已处理过",
                            "report_platform_filtered": "报错平台不在自动处理范围内",
                        }.get(reason, f"已跳过：{reason or '未知原因'}")
                        self._record_action(
                            record_id=rid,
                            merchant_code=merchant_code,
                            status="skipped",
                            message=msg,
                        )
                    else:
                        err = str(outcome.get("error") or "自动跑链路失败")
                        self._record_action(
                            record_id=rid,
                            merchant_code=merchant_code,
                            status="failed",
                            message=err,
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

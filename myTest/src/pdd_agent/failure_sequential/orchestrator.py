"""分阶段流水线编排：批次同步、阶段推进、单条串行执行。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.core.account_display import resolve_cycle_relist_account_id
from pdd_agent.core.logging import get_logger
from pdd_agent.db.models import FailureSequentialJobORM
from pdd_agent.failure_sequential import constants as C
from pdd_agent.failure_sequential.repository import (
    batch_to_dict,
    create_batch,
    get_active_batch,
    has_completed_feishu_job,
    insert_job,
    job_exists_for_feishu,
    job_ready_for_limited_time,
    list_jobs_by_batch,
    listing_phase_complete,
    mark_job_completed_if_done,
    patch_job,
    pick_next_post_listing_job,
    promotion_phase_complete,
    update_batch_stats,
    _refresh_batch_counters,
)
from pdd_agent.failure_sequential.runner import (
    default_activity_ids,
    run_activity_stage,
    run_limited_time_stage,
    run_listing_stage,
    run_promotion_stage,
)
from pdd_agent.integrations.feishu.config import (
    PddFailureCycleRelistWatchConfig,
    load_feishu_config,
)
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger import (
    resolve_listing_selectors_for_merchant_code,
)
from pdd_agent.integrations.feishu.pdd_failure_log_watch import list_cycle_relist_candidates

logger = get_logger(__name__)


def _activity_delay_minutes(watch: PddFailureCycleRelistWatchConfig) -> int:
    return max(0, int(watch.sequential_activity_delay_minutes or 0))


def _stamp_limited_time_completed(job: FailureSequentialJobORM) -> datetime:
    if job.limited_time_completed_at:
        return job.limited_time_completed_at
    return datetime.now()


def _patch_limited_time_terminal(
    job: FailureSequentialJobORM,
    *,
    status: str,
    error: str = "",
    run_id: str = "",
) -> None:
    completed_at = _stamp_limited_time_completed(job)
    patch_job(
        job.job_id,
        limited_time_status=status,
        limited_time_error=error,
        limited_time_run_id=run_id,
        limited_time_completed_at=completed_at,
        current_phase=C.PHASE_ACTIVITY_618,
    )


def _filter_candidate(
    item: dict[str, Any],
    watch: PddFailureCycleRelistWatchConfig,
) -> tuple[bool, str]:
    allowed = {str(x).strip() for x in (watch.pipeline_report_platforms or []) if str(x).strip()}
    platform = str(item.get("report_platform") or "").strip()
    if allowed and platform and platform not in allowed:
        return False, "report_platform_filtered"
    record_id = str(item.get("record_id") or "").strip()
    merchant_code = str(item.get("merchant_code") or "").strip()
    if not record_id:
        return False, "missing_record_id"
    if not merchant_code:
        return False, "missing_merchant_code"
    return True, ""


def _resolve_account(item: dict[str, Any]) -> tuple[str, str]:
    account_id, err = resolve_cycle_relist_account_id(
        account_name=str(item.get("account_name") or "").strip(),
        account_id=str(item.get("account_id") or "").strip(),
    )
    return account_id or "", err or ""


def sync_batch_candidates(
    candidates: list[dict[str, Any]],
    *,
    watch: PddFailureCycleRelistWatchConfig,
    batch_id: str,
) -> int:
    material_source = str(watch.pipeline_material_source or "minio").strip() or "minio"
    added = 0
    for item in candidates:
        ok, _reason = _filter_candidate(item, watch)
        if not ok:
            continue
        record_id = str(item.get("record_id") or "").strip()
        if job_exists_for_feishu(record_id, batch_id):
            continue
        if has_completed_feishu_job(record_id):
            continue
        account_id, account_error = _resolve_account(item)
        if not account_id:
            logger.warning(
                "sequential skip candidate record_id=%s account_error=%s",
                record_id,
                account_error,
            )
            continue
        merchant_code = str(item.get("merchant_code") or "").strip()
        product_codes = resolve_listing_selectors_for_merchant_code(
            merchant_code,
            material_source=material_source,
        )
        insert_job(
            batch_id=batch_id,
            feishu_record_id=record_id,
            merchant_code=merchant_code,
            account_id=account_id,
            account_name=str(item.get("account_name") or "").strip(),
            failure_reason=str(item.get("failure_reason") or "").strip(),
            report_platform=str(item.get("report_platform") or "").strip(),
            product_codes=product_codes or [merchant_code],
        )
        added += 1
    return added


def _pick_listing_job(jobs: list[FailureSequentialJobORM]) -> FailureSequentialJobORM | None:
    for job in jobs:
        if job.listing_status == C.STAGE_PENDING:
            return job
    return None


def _run_post_listing_step(
    *,
    batch_id: str,
    jobs: list[FailureSequentialJobORM],
    job: FailureSequentialJobORM,
    step: str,
    watch: PddFailureCycleRelistWatchConfig,
    activity_618_id: str,
    activity_discount_id: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    if step == "limited_time":
        summary.update(action="limited_time", job_id=job.job_id, phase=C.PHASE_LIMITED_TIME)
        patch_job(job.job_id, limited_time_status=C.STAGE_RUNNING, current_phase=C.PHASE_LIMITED_TIME)
        outcome = run_limited_time_stage(job)
        _patch_limited_time_terminal(
            job,
            status=str(outcome.get("status") or C.STAGE_FAILED),
            error=str(outcome.get("error") or ""),
            run_id=str(outcome.get("run_id") or ""),
        )
        return summary

    if step == "activity_618":
        summary.update(action="activity_618", job_id=job.job_id, phase=C.PHASE_ACTIVITY_618)
        patch_job(job.job_id, activity_618_status=C.STAGE_RUNNING, current_phase=C.PHASE_ACTIVITY_618)
        outcome = run_activity_stage(job, activity_id=activity_618_id)
        patch_job(
            job.job_id,
            activity_618_status=outcome.get("status") or C.STAGE_FAILED,
            activity_618_error=str(outcome.get("error") or ""),
            activity_618_run_id=str(outcome.get("run_id") or ""),
            current_phase=C.PHASE_ACTIVITY_DISCOUNT,
        )
        return summary

    if step == "discount":
        summary.update(action="activity_discount", job_id=job.job_id, phase=C.PHASE_ACTIVITY_DISCOUNT)
        patch_job(
            job.job_id,
            activity_discount_status=C.STAGE_RUNNING,
            current_phase=C.PHASE_ACTIVITY_DISCOUNT,
        )
        outcome = run_activity_stage(job, activity_id=activity_discount_id)
        patch_job(
            job.job_id,
            activity_discount_status=outcome.get("status") or C.STAGE_FAILED,
            activity_discount_error=str(outcome.get("error") or ""),
            activity_discount_run_id=str(outcome.get("run_id") or ""),
            current_phase=C.PHASE_PROMOTION,
        )
        return summary

    if step == "promotion":
        summary.update(action="promotion", job_id=job.job_id, phase=C.PHASE_PROMOTION)
        patch_job(job.job_id, promotion_status=C.STAGE_RUNNING, current_phase=C.PHASE_PROMOTION)
        outcome = run_promotion_stage(job)
        patch_job(
            job.job_id,
            promotion_status=outcome.get("status") or C.STAGE_FAILED,
            promotion_error=str(outcome.get("error") or ""),
            promotion_run_id=str(outcome.get("run_id") or ""),
            current_phase=C.PHASE_COMPLETED,
        )
        refreshed = list_jobs_by_batch(batch_id)
        for j in refreshed:
            if j.job_id == job.job_id:
                mark_job_completed_if_done(j)
        return summary

    summary["action"] = step
    return summary


def tick_once() -> dict[str, Any]:
    """执行一步（单条任务的一个阶段）；永不向外抛异常。"""
    summary: dict[str, Any] = {
        "ok": True,
        "action": "idle",
        "batch_id": "",
        "job_id": "",
        "phase": "",
        "error": "",
    }
    try:
        cfg = load_feishu_config()
        watch = cfg.pdd_upload_log.failure_cycle_relist_watch
        if not watch.enabled or not watch.sequential_staged_enabled:
            summary["action"] = "disabled"
            return summary

        delay_minutes = _activity_delay_minutes(watch)
        batch = get_active_batch()
        if not batch:
            poll = list_cycle_relist_candidates(config=cfg, watch=watch)
            items = list(poll.get("items") or [])
            if not items:
                summary["action"] = "no_candidates"
                return summary
            batch = create_batch(len(items))
            added = sync_batch_candidates(items, watch=watch, batch_id=batch.batch_id)
            update_batch_stats(batch.batch_id, job_count=added)
            if added <= 0:
                update_batch_stats(batch.batch_id, status=C.BATCH_COMPLETED)
                summary.update(action="empty_batch", batch_id=batch.batch_id)
                return summary
            logger.info(
                "failure sequential batch started batch_id=%s jobs=%s",
                batch.batch_id,
                added,
            )

        batch_id = batch.batch_id
        jobs = list_jobs_by_batch(batch_id)
        if not jobs:
            update_batch_stats(batch_id, status=C.BATCH_COMPLETED)
            summary.update(action="no_jobs", batch_id=batch_id)
            return summary

        summary["batch_id"] = batch_id
        activity_618_id, activity_discount_id = default_activity_ids(watch)

        if not listing_phase_complete(jobs):
            job = _pick_listing_job(jobs)
            if not job:
                _refresh_batch_counters(batch_id, jobs)
                summary["action"] = "listing_wait"
                return summary
            summary.update(action="listing", job_id=job.job_id, phase=C.PHASE_LISTING)
            patch_job(job.job_id, listing_status=C.STAGE_RUNNING, current_phase=C.PHASE_LISTING)
            outcome = run_listing_stage(job, watch=watch)
            patch_job(
                job.job_id,
                listing_status=outcome.get("status") or C.STAGE_FAILED,
                listing_error=str(outcome.get("error") or ""),
                listing_run_id=str(outcome.get("run_id") or ""),
                pdd_product_id=str(outcome.get("pdd_product_id") or ""),
                mapping_id=str(outcome.get("mapping_id") or ""),
                current_phase=C.PHASE_LIMITED_TIME
                if (outcome.get("status") or C.STAGE_FAILED) in C.TERMINAL_STAGES
                else C.PHASE_LISTING,
            )
            _refresh_batch_counters(batch_id, list_jobs_by_batch(batch_id))
            return summary

        for job in jobs:
            if job.limited_time_status == C.STAGE_PENDING and not job_ready_for_limited_time(job):
                _patch_limited_time_terminal(
                    job,
                    status=C.STAGE_SKIPPED,
                    error="上架未成功，跳过限时限量购",
                )

        jobs = list_jobs_by_batch(batch_id)
        next_job, step = pick_next_post_listing_job(jobs, delay_minutes)
        if step in {"activity_wait", "idle"} and promotion_phase_complete(jobs):
            for j in jobs:
                if j.overall_status != C.OVERALL_COMPLETED:
                    mark_job_completed_if_done(j)
            jobs = list_jobs_by_batch(batch_id)
            _refresh_batch_counters(batch_id, jobs)
            if all(j.overall_status == C.OVERALL_COMPLETED for j in jobs):
                update_batch_stats(batch_id, status=C.BATCH_COMPLETED)
                summary["action"] = "batch_completed"
            else:
                summary["action"] = "finalize"
            return summary

        if step in {"activity_wait", "idle"}:
            _refresh_batch_counters(batch_id, jobs)
            summary["action"] = step
            return summary

        assert next_job is not None
        _run_post_listing_step(
            batch_id=batch_id,
            jobs=jobs,
            job=next_job,
            step=step,
            watch=watch,
            activity_618_id=activity_618_id,
            activity_discount_id=activity_discount_id,
            summary=summary,
        )
        _refresh_batch_counters(batch_id, list_jobs_by_batch(batch_id))
        return summary
    except Exception as exc:
        logger.exception("failure sequential tick failed")
        summary.update(ok=False, action="error", error=str(exc))
        return summary


def is_batch_active() -> bool:
    return get_active_batch() is not None


def get_batch_status() -> dict[str, Any]:
    return batch_to_dict(get_active_batch())

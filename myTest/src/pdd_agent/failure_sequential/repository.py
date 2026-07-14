"""分阶段流水线数据库读写。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from pdd_agent.db.models import FailureSequentialBatchORM, FailureSequentialJobORM
from pdd_agent.db.session import session_scope
from pdd_agent.failure_sequential.constants import (
    BATCH_COMPLETED,
    BATCH_LISTING,
    BATCH_POST_LISTING,
    OVERALL_ACTIVE,
    OVERALL_COMPLETED,
    PHASE_COMPLETED,
    PHASE_LISTING,
    STAGE_PENDING,
    STAGE_SKIPPED,
    STAGE_SUCCESS,
    TERMINAL_STAGES,
)


def _new_batch_id() -> str:
    return datetime.now().strftime("fsb_%Y%m%d_%H%M%S_") + uuid4().hex[:8]


def get_active_batch() -> FailureSequentialBatchORM | None:
    with session_scope() as session:
        row = session.execute(
            select(FailureSequentialBatchORM)
            .where(FailureSequentialBatchORM.status != BATCH_COMPLETED)
            .order_by(FailureSequentialBatchORM.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row:
            session.expunge(row)
        return row


def create_batch(job_count: int) -> FailureSequentialBatchORM:
    batch_id = _new_batch_id()
    now = datetime.now()
    row = FailureSequentialBatchORM(
        batch_id=batch_id,
        status=BATCH_LISTING,
        job_count=int(job_count),
        started_at=now,
        updated_at=now,
    )
    with session_scope() as session:
        session.add(row)
        session.flush()
        session.expunge(row)
    return row


def get_batch(batch_id: str) -> FailureSequentialBatchORM | None:
    with session_scope() as session:
        row = session.get(FailureSequentialBatchORM, batch_id)
        if row:
            session.expunge(row)
        return row


def update_batch_stats(
    batch_id: str,
    *,
    status: str | None = None,
    listing_done: int | None = None,
    limited_time_done: int | None = None,
    activity_done: int | None = None,
    promotion_done: int | None = None,
    completed_count: int | None = None,
    last_error: str | None = None,
    activity_unlocked: bool | None = None,
    activity_scheduled_at: datetime | None = None,
    activity_unlocked_at: datetime | None = None,
) -> None:
    values: dict[str, Any] = {"updated_at": datetime.now()}
    if status is not None:
        values["status"] = status
    if listing_done is not None:
        values["listing_done"] = listing_done
    if limited_time_done is not None:
        values["limited_time_done"] = limited_time_done
    if activity_done is not None:
        values["activity_done"] = activity_done
    if promotion_done is not None:
        values["promotion_done"] = promotion_done
    if completed_count is not None:
        values["completed_count"] = completed_count
    if last_error is not None:
        values["last_error"] = last_error[:2000]
    if activity_unlocked is not None:
        values["activity_unlocked"] = bool(activity_unlocked)
    if activity_scheduled_at is not None:
        values["activity_scheduled_at"] = activity_scheduled_at
    if activity_unlocked_at is not None:
        values["activity_unlocked_at"] = activity_unlocked_at
    with session_scope() as session:
        session.execute(
            update(FailureSequentialBatchORM)
            .where(FailureSequentialBatchORM.batch_id == batch_id)
            .values(**values)
        )


def unlock_batch_activities(batch_id: str) -> None:
    now = datetime.now()
    update_batch_stats(
        batch_id,
        activity_unlocked=True,
        activity_unlocked_at=now,
        status=BATCH_POST_LISTING,
    )


def schedule_batch_activities(batch_id: str, run_at: datetime) -> None:
    update_batch_stats(
        batch_id,
        activity_scheduled_at=run_at,
        status=BATCH_AWAITING_ACTIVITY,
    )


def list_jobs_by_batch(batch_id: str) -> list[FailureSequentialJobORM]:
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(FailureSequentialJobORM)
                .where(FailureSequentialJobORM.batch_id == batch_id)
                .order_by(FailureSequentialJobORM.created_at.asc())
            ).all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def list_recent_jobs(*, limit: int = 100) -> list[FailureSequentialJobORM]:
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(FailureSequentialJobORM)
                .order_by(FailureSequentialJobORM.updated_at.desc())
                .limit(limit)
            ).all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def get_job(job_id: str) -> FailureSequentialJobORM | None:
    with session_scope() as session:
        row = session.get(FailureSequentialJobORM, job_id)
        if row:
            session.expunge(row)
        return row


def job_exists_for_feishu(feishu_record_id: str, batch_id: str) -> bool:
    with session_scope() as session:
        row = session.execute(
            select(FailureSequentialJobORM.job_id)
            .where(
                FailureSequentialJobORM.batch_id == batch_id,
                FailureSequentialJobORM.feishu_record_id == feishu_record_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        return row is not None


def has_completed_feishu_job(feishu_record_id: str) -> bool:
    with session_scope() as session:
        row = session.execute(
            select(FailureSequentialJobORM.job_id)
            .where(
                FailureSequentialJobORM.feishu_record_id == feishu_record_id,
                FailureSequentialJobORM.overall_status == OVERALL_COMPLETED,
            )
            .limit(1)
        ).scalar_one_or_none()
        return row is not None


def insert_job(
    *,
    batch_id: str,
    feishu_record_id: str,
    merchant_code: str,
    account_id: str,
    account_name: str,
    failure_reason: str,
    report_platform: str,
    product_codes: list[str],
) -> FailureSequentialJobORM:
    job_id = uuid4().hex
    row = FailureSequentialJobORM(
        job_id=job_id,
        batch_id=batch_id,
        feishu_record_id=feishu_record_id,
        merchant_code=merchant_code,
        account_id=account_id,
        account_name=account_name,
        failure_reason=failure_reason,
        report_platform=report_platform,
        product_codes=list(product_codes or []),
        current_phase=PHASE_LISTING,
        overall_status=OVERALL_ACTIVE,
        listing_status=STAGE_PENDING,
        limited_time_status=STAGE_PENDING,
        activity_618_status=STAGE_PENDING,
        activity_discount_status=STAGE_PENDING,
        promotion_status=STAGE_PENDING,
    )
    with session_scope() as session:
        session.add(row)
        session.flush()
        session.expunge(row)
    return row


def patch_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = datetime.now()
    with session_scope() as session:
        session.execute(
            update(FailureSequentialJobORM)
            .where(FailureSequentialJobORM.job_id == job_id)
            .values(**fields)
        )


def _resolve_batch_status(jobs: list[FailureSequentialJobORM]) -> str:
    if not jobs:
        return BATCH_COMPLETED
    completed = sum(1 for j in jobs if j.overall_status == OVERALL_COMPLETED)
    if completed >= len(jobs):
        return BATCH_COMPLETED
    if not listing_phase_complete(jobs):
        return BATCH_LISTING
    return BATCH_POST_LISTING


def _refresh_batch_counters(batch_id: str, jobs: list[FailureSequentialJobORM]) -> None:
    listing_done = sum(1 for j in jobs if j.listing_status in TERMINAL_STAGES)
    ltd_done = sum(1 for j in jobs if j.limited_time_status in TERMINAL_STAGES)
    act_done = sum(
        1
        for j in jobs
        if j.activity_618_status in TERMINAL_STAGES
        and j.activity_discount_status in TERMINAL_STAGES
    )
    promo_done = sum(1 for j in jobs if j.promotion_status in TERMINAL_STAGES)
    completed = sum(1 for j in jobs if j.overall_status == OVERALL_COMPLETED)
    status = _resolve_batch_status(jobs)
    update_batch_stats(
        batch_id,
        status=status,
        listing_done=listing_done,
        limited_time_done=ltd_done,
        activity_done=act_done,
        promotion_done=promo_done,
        completed_count=completed,
    )


def batch_to_dict(batch: FailureSequentialBatchORM | None) -> dict[str, Any]:
    if not batch:
        return {}
    return {
        "batch_id": batch.batch_id,
        "status": batch.status,
        "job_count": batch.job_count,
        "listing_done": batch.listing_done,
        "limited_time_done": batch.limited_time_done,
        "activity_done": batch.activity_done,
        "promotion_done": batch.promotion_done,
        "completed_count": batch.completed_count,
    }


def job_to_dict(job: FailureSequentialJobORM) -> dict[str, Any]:
    ltd_completed = ""
    if job.limited_time_completed_at:
        ltd_completed = job.limited_time_completed_at.isoformat(timespec="seconds")
    return {
        "job_id": job.job_id,
        "limited_time_completed_at": ltd_completed,
    }


def activity_due_at(
    job: FailureSequentialJobORM,
    delay_minutes: int,
) -> datetime | None:
    if job.limited_time_status not in TERMINAL_STAGES:
        return None
    completed_at = job.limited_time_completed_at
    if completed_at is None:
        return datetime.now()
    return completed_at + timedelta(minutes=max(0, int(delay_minutes)))


def job_activity_618_due(job: FailureSequentialJobORM, delay_minutes: int) -> bool:
    if not job_ready_for_activity(job):
        return False
    due = activity_due_at(job, delay_minutes)
    if due is None:
        return False
    return datetime.now() >= due


def pick_next_post_listing_job(
    jobs: list[FailureSequentialJobORM],
    delay_minutes: int,
) -> tuple[FailureSequentialJobORM | None, str]:
    """按创建顺序挑选下一条可执行的后置步骤（推广>七折>618>限时限量购）。"""
    for job in jobs:
        if job_ready_for_promotion(job):
            return job, "promotion"
    for job in jobs:
        if job_ready_for_discount(job):
            return job, "discount"
    for job in jobs:
        if job_activity_618_due(job, delay_minutes):
            return job, "activity_618"
    for job in jobs:
        if job_ready_for_limited_time(job):
            return job, "limited_time"
    waiting = any(
        job_ready_for_activity(job) and not job_activity_618_due(job, delay_minutes)
        for job in jobs
    )
    if waiting:
        return None, "activity_wait"
    return None, "idle"


def has_active_batch() -> bool:
    return get_active_batch() is not None


def listing_phase_complete(jobs: list[FailureSequentialJobORM]) -> bool:
    if not jobs:
        return True
    return all(j.listing_status in TERMINAL_STAGES for j in jobs)


def limited_time_phase_complete(jobs: list[FailureSequentialJobORM]) -> bool:
    if not jobs:
        return True
    return all(j.limited_time_status in TERMINAL_STAGES for j in jobs)


def activities_phase_complete(jobs: list[FailureSequentialJobORM]) -> bool:
    if not jobs:
        return True
    return all(
        j.activity_618_status in TERMINAL_STAGES
        and j.activity_discount_status in TERMINAL_STAGES
        for j in jobs
    )


def promotion_phase_complete(jobs: list[FailureSequentialJobORM]) -> bool:
    if not jobs:
        return True
    return all(j.promotion_status in TERMINAL_STAGES for j in jobs)


def job_ready_for_limited_time(job: FailureSequentialJobORM) -> bool:
    return (
        job.listing_status in {STAGE_SUCCESS, STAGE_SKIPPED}
        and bool(str(job.pdd_product_id or "").strip())
        and job.limited_time_status == STAGE_PENDING
    )


def job_ready_for_activity(job: FailureSequentialJobORM) -> bool:
    return (
        job.limited_time_status in TERMINAL_STAGES
        and job.activity_618_status == STAGE_PENDING
    )


def job_ready_for_discount(job: FailureSequentialJobORM) -> bool:
    return (
        job.activity_618_status in TERMINAL_STAGES
        and job.activity_discount_status == STAGE_PENDING
    )


def job_ready_for_promotion(job: FailureSequentialJobORM) -> bool:
    return (
        job.activity_discount_status in TERMINAL_STAGES
        and job.promotion_status == STAGE_PENDING
    )


def mark_job_completed_if_done(job: FailureSequentialJobORM) -> bool:
    if job.promotion_status not in TERMINAL_STAGES:
        return False
    patch_job(
        job.job_id,
        current_phase=PHASE_COMPLETED,
        overall_status=OVERALL_COMPLETED,
    )
    return True

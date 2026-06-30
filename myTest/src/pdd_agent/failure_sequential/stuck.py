"""分阶段流水线：检测并重置卡死在 running 的任务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select

from pdd_agent.db.models import FailureSequentialJobORM
from pdd_agent.db.session import session_scope
from pdd_agent.domain.enums import RunStatus
from pdd_agent.failure_sequential.constants import (
    PHASE_ACTIVITY_618,
    PHASE_ACTIVITY_DISCOUNT,
    PHASE_LIMITED_TIME,
    PHASE_LISTING,
    PHASE_PROMOTION,
    STAGE_PENDING,
    STAGE_RUNNING,
)
from pdd_agent.failure_sequential.repository import get_job, patch_job
from pdd_agent.storage.task_store import TaskRunStore

STAGE_LABELS: dict[str, str] = {
    "listing": "上架",
    "limited_time": "限时限量购",
    "activity_618": "618",
    "activity_discount": "七折",
    "promotion": "推广",
}

_STAGE_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    ("listing", "listing_status", "listing_run_id", "listing_error", PHASE_LISTING),
    (
        "limited_time",
        "limited_time_status",
        "limited_time_run_id",
        "limited_time_error",
        PHASE_LIMITED_TIME,
    ),
    (
        "activity_618",
        "activity_618_status",
        "activity_618_run_id",
        "activity_618_error",
        PHASE_ACTIVITY_618,
    ),
    (
        "activity_discount",
        "activity_discount_status",
        "activity_discount_run_id",
        "activity_discount_error",
        PHASE_ACTIVITY_DISCOUNT,
    ),
    ("promotion", "promotion_status", "promotion_run_id", "promotion_error", PHASE_PROMOTION),
)


@dataclass(frozen=True)
class StuckStage:
    stage: str
    label: str
    run_id: str
    reason: str


@dataclass(frozen=True)
class StuckJob:
    job_id: str
    batch_id: str
    merchant_code: str
    account_name: str
    updated_at: str
    stuck_stages: tuple[StuckStage, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "batch_id": self.batch_id,
            "merchant_code": self.merchant_code,
            "account_name": self.account_name,
            "updated_at": self.updated_at,
            "stuck_stages": [
                {
                    "stage": s.stage,
                    "label": s.label,
                    "run_id": s.run_id,
                    "reason": s.reason,
                }
                for s in self.stuck_stages
            ],
        }


def _run_is_active(run_id: str) -> bool:
    run_id = str(run_id or "").strip()
    if not run_id:
        return False
    record = TaskRunStore().load(run_id)
    if not record:
        return False
    return record.status == RunStatus.RUNNING


def _stuck_reason(run_id: str) -> str:
    run_id = str(run_id or "").strip()
    if not run_id:
        return "无 run_id，服务可能已重启"
    record = TaskRunStore().load(run_id)
    if not record:
        return "run 记录不存在"
    return f"run 已结束（{record.status.value}）"


def detect_stuck_stages(job: FailureSequentialJobORM) -> list[StuckStage]:
    stuck: list[StuckStage] = []
    for stage, status_field, run_field, _, _ in _STAGE_SPECS:
        if getattr(job, status_field) != STAGE_RUNNING:
            continue
        run_id = str(getattr(job, run_field) or "").strip()
        if _run_is_active(run_id):
            continue
        stuck.append(
            StuckStage(
                stage=stage,
                label=STAGE_LABELS.get(stage, stage),
                run_id=run_id,
                reason=_stuck_reason(run_id),
            )
        )
    return stuck


def _job_updated_at(job: FailureSequentialJobORM) -> str:
    updated = getattr(job, "updated_at", None)
    if not updated:
        return ""
    return updated.isoformat(timespec="seconds")


def _to_stuck_job(job: FailureSequentialJobORM, stages: list[StuckStage]) -> StuckJob:
    return StuckJob(
        job_id=job.job_id,
        batch_id=job.batch_id,
        merchant_code=str(job.merchant_code or ""),
        account_name=str(job.account_name or ""),
        updated_at=_job_updated_at(job),
        stuck_stages=tuple(stages),
    )


def list_stuck_jobs(*, limit: int = 100) -> list[StuckJob]:
    max_items = max(1, min(int(limit), 500))
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(FailureSequentialJobORM)
                .where(
                    or_(
                        FailureSequentialJobORM.listing_status == STAGE_RUNNING,
                        FailureSequentialJobORM.limited_time_status == STAGE_RUNNING,
                        FailureSequentialJobORM.activity_618_status == STAGE_RUNNING,
                        FailureSequentialJobORM.activity_discount_status == STAGE_RUNNING,
                        FailureSequentialJobORM.promotion_status == STAGE_RUNNING,
                    )
                )
                .order_by(FailureSequentialJobORM.updated_at.desc())
                .limit(max_items * 3)
            ).all()
        )
        for row in rows:
            session.expunge(row)

    stuck_jobs: list[StuckJob] = []
    for row in rows:
        stages = detect_stuck_stages(row)
        if stages:
            stuck_jobs.append(_to_stuck_job(row, stages))
        if len(stuck_jobs) >= max_items:
            break
    return stuck_jobs


def reset_stuck_jobs(*, limit: int = 100) -> list[StuckJob]:
    targets = list_stuck_jobs(limit=limit)
    reset_items: list[StuckJob] = []
    for item in targets:
        job = get_job(item.job_id)
        if not job:
            continue
        stages = detect_stuck_stages(job)
        if not stages:
            continue
        stage_names = {s.stage for s in stages}
        patches: dict[str, Any] = {}
        for stage, status_field, run_field, error_field, phase in _STAGE_SPECS:
            if stage not in stage_names:
                continue
            patches[status_field] = STAGE_PENDING
            patches[run_field] = ""
            patches[error_field] = ""
            if "current_phase" not in patches:
                patches["current_phase"] = phase
        patch_job(item.job_id, **patches)
        reset_items.append(item)
    return reset_items

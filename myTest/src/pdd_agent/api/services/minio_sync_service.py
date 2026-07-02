"""MinIO 素材异步同步到本地缓存。"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.config import load_minio_config, minio_configured
from pdd_agent.integrations.minio.staging import _sets_for_product_inputs, stage_minio_image_set

logger = get_logger(__name__)

_JOB_LOCK = threading.Lock()
_JOBS: dict[str, "MinioSyncJob"] = {}
_ACTIVE_JOB_ID: str = ""


@dataclass
class MinioSyncJob:
    job_id: str
    product_codes: list[str]
    status: str = "pending"  # pending | running | success | failed
    total_sets: int = 0
    completed_sets: int = 0
    current_label: str = ""
    downloaded_files: int = 0
    skipped_files: int = 0
    pruned_dirs: int = 0
    pruned_files: int = 0
    pruned_sets: int = 0
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    sets: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        if self.status == "success":
            percent = 100.0
        elif self.status == "running" and self.total_sets:
            percent = round(100.0 * self.completed_sets / self.total_sets, 1)
        else:
            percent = 0.0
        return {
            "job_id": self.job_id,
            "status": self.status,
            "product_codes": list(self.product_codes),
            "total_sets": self.total_sets,
            "completed_sets": self.completed_sets,
            "current_label": self.current_label,
            "downloaded_files": self.downloaded_files,
            "skipped_files": self.skipped_files,
            "pruned_dirs": self.pruned_dirs,
            "pruned_files": self.pruned_files,
            "pruned_sets": self.pruned_sets,
            "error": self.error,
            "progress_percent": percent,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def get_minio_sync_job(job_id: str) -> MinioSyncJob | None:
    with _JOB_LOCK:
        return _JOBS.get(str(job_id or "").strip())


def get_active_minio_sync_job() -> MinioSyncJob | None:
    with _JOB_LOCK:
        if not _ACTIVE_JOB_ID:
            return None
        return _JOBS.get(_ACTIVE_JOB_ID)


def _prune_old_jobs() -> None:
    cutoff = time.time() - 3600
    stale = [job_id for job_id, job in _JOBS.items() if job.finished_at and job.finished_at < cutoff]
    for job_id in stale:
        _JOBS.pop(job_id, None)


def start_minio_sync_job(product_codes: list[str]) -> MinioSyncJob:
    global _ACTIVE_JOB_ID

    if not minio_configured():
        raise RuntimeError("MinIO 未配置，请填写 config/minio.yaml")

    codes = [str(code or "").strip() for code in product_codes if str(code or "").strip()]
    if not codes:
        raise ValueError("请至少提供一个商品编码")

    cfg = load_minio_config()
    sets = sorted(_sets_for_product_inputs(codes, cfg))
    if not sets:
        raise ValueError("未找到可同步的套图，请确认 MinIO 索引已刷新")

    with _JOB_LOCK:
        _prune_old_jobs()
        active = _JOBS.get(_ACTIVE_JOB_ID) if _ACTIVE_JOB_ID else None
        if active and active.status in {"pending", "running"}:
            raise RuntimeError(
                f"已有同步任务进行中（{active.completed_sets}/{active.total_sets}），请稍候"
            )

        job_id = uuid.uuid4().hex
        job = MinioSyncJob(
            job_id=job_id,
            product_codes=codes,
            total_sets=len(sets),
            sets=sets,
        )
        _JOBS[job_id] = job
        _ACTIVE_JOB_ID = job_id

    thread = threading.Thread(target=_run_sync_job, args=(job_id,), daemon=True)
    thread.start()
    return job


def _run_sync_job(job_id: str) -> None:
    global _ACTIVE_JOB_ID

    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = time.time()

    cfg = load_minio_config()
    try:
        for index, (family_code, image_set) in enumerate(job.sets, start=1):
            with _JOB_LOCK:
                if job.status == "failed":
                    return
                job.current_label = f"{family_code}/{image_set}"
            downloaded, skipped, pruned_dirs, pruned_files, pruned_sets, mismatches = stage_minio_image_set(
                family_code=family_code,
                image_set=image_set,
                config=cfg,
            )
            with _JOB_LOCK:
                job.completed_sets = index
                job.downloaded_files += downloaded
                job.skipped_files += skipped
                job.pruned_dirs += pruned_dirs
                job.pruned_files += pruned_files
                job.pruned_sets += pruned_sets
            if mismatches:
                preview = "；".join(mismatches[:3])
                if len(mismatches) > 3:
                    preview += f" 等 {len(mismatches)} 项"
                raise RuntimeError(f"MinIO 与本地缓存图片数量不一致：{preview}")
        with _JOB_LOCK:
            job.status = "success"
            job.current_label = ""
            job.finished_at = time.time()
        logger.info(
            "minio sync job %s done sets=%s downloaded=%s skipped=%s pruned_dirs=%s pruned_files=%s pruned_sets=%s",
            job_id,
            job.total_sets,
            job.downloaded_files,
            job.skipped_files,
            job.pruned_dirs,
            job.pruned_files,
            job.pruned_sets,
        )
    except Exception as exc:
        logger.exception("minio sync job %s failed", job_id)
        with _JOB_LOCK:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = time.time()
    finally:
        with _JOB_LOCK:
            if _ACTIVE_JOB_ID == job_id:
                _ACTIVE_JOB_ID = ""

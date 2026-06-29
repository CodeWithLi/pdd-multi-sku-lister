"""MinIO 异步同步任务测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pdd_agent.api.services import minio_sync_service


@pytest.fixture(autouse=True)
def reset_sync_jobs():
    with minio_sync_service._JOB_LOCK:
        minio_sync_service._JOBS.clear()
        minio_sync_service._ACTIVE_JOB_ID = ""
    yield
    with minio_sync_service._JOB_LOCK:
        minio_sync_service._JOBS.clear()
        minio_sync_service._ACTIVE_JOB_ID = ""


def test_start_minio_sync_job_returns_immediately(monkeypatch):
    monkeypatch.setattr(minio_sync_service, "minio_configured", lambda: True)
    monkeypatch.setattr(
        minio_sync_service,
        "_sets_for_product_inputs",
        lambda codes, cfg: [("BD023", "第一套图")],
    )

    class NoopThread:
        def __init__(self, target, args=(), daemon=True):
            pass

        def start(self):
            return None

    monkeypatch.setattr(minio_sync_service.threading, "Thread", NoopThread)

    job = minio_sync_service.start_minio_sync_job(["BD023A"])
    assert job.job_id
    assert job.status == "pending"
    assert job.total_sets == 1


def test_start_minio_sync_job_rejects_concurrent(monkeypatch):
    monkeypatch.setattr(minio_sync_service, "minio_configured", lambda: True)
    monkeypatch.setattr(
        minio_sync_service,
        "_sets_for_product_inputs",
        lambda codes, cfg: [("BD023", "第一套图")],
    )

    class NoopThread:
        def __init__(self, target, args=(), daemon=True):
            pass

        def start(self):
            return None

    monkeypatch.setattr(minio_sync_service.threading, "Thread", NoopThread)

    minio_sync_service.start_minio_sync_job(["BD023A"])
    with minio_sync_service._JOB_LOCK:
        active = minio_sync_service._JOBS[minio_sync_service._ACTIVE_JOB_ID]
        active.status = "running"

    with pytest.raises(RuntimeError, match="已有同步任务进行中"):
        minio_sync_service.start_minio_sync_job(["BD025A"])


def test_run_sync_job_updates_progress(monkeypatch):
    monkeypatch.setattr(
        minio_sync_service,
        "stage_minio_image_set",
        lambda **kwargs: (3, 2, 1, 4, []),
    )

    job = minio_sync_service.MinioSyncJob(
        job_id="abc",
        product_codes=["BD023A"],
        total_sets=2,
        sets=[("BD023", "第一套图"), ("BD025", "第一套图")],
    )
    with minio_sync_service._JOB_LOCK:
        minio_sync_service._JOBS["abc"] = job

    minio_sync_service._run_sync_job("abc")

    result = minio_sync_service.get_minio_sync_job("abc")
    assert result is not None
    assert result.status == "success"
    assert result.completed_sets == 2
    assert result.downloaded_files == 6
    assert result.skipped_files == 4
    assert result.pruned_dirs == 2
    assert result.pruned_files == 8

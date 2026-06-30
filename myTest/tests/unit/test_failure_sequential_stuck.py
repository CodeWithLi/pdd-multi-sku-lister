"""分阶段卡死任务检测与重置测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.domain.enums import RunStatus
from pdd_agent.failure_sequential.constants import STAGE_PENDING, STAGE_RUNNING
from pdd_agent.failure_sequential.stuck import detect_stuck_stages, reset_stuck_jobs


def _job(**kwargs):
    defaults = {
        "job_id": "job1",
        "batch_id": "batch1",
        "merchant_code": "BD023A",
        "account_name": "兔兔潮玩屋",
        "listing_status": STAGE_PENDING,
        "listing_run_id": "",
        "limited_time_status": STAGE_PENDING,
        "limited_time_run_id": "",
        "activity_618_status": STAGE_PENDING,
        "activity_618_run_id": "",
        "activity_discount_status": STAGE_PENDING,
        "activity_discount_run_id": "",
        "promotion_status": STAGE_PENDING,
        "promotion_run_id": "",
        "updated_at": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_detect_stuck_listing_without_run_id():
    job = _job(listing_status=STAGE_RUNNING, listing_run_id="")
    stuck = detect_stuck_stages(job)
    assert len(stuck) == 1
    assert stuck[0].stage == "listing"
    assert stuck[0].reason == "无 run_id，服务可能已重启"


def test_detect_not_stuck_when_run_still_running():
    job = _job(listing_status=STAGE_RUNNING, listing_run_id="run-1")
    record = SimpleNamespace(status=RunStatus.RUNNING)
    with patch("pdd_agent.failure_sequential.stuck.TaskRunStore") as store_cls:
        store_cls.return_value.load.return_value = record
        stuck = detect_stuck_stages(job)
    assert stuck == []


def test_detect_stuck_when_run_finished():
    job = _job(listing_status=STAGE_RUNNING, listing_run_id="run-1")
    record = SimpleNamespace(status=RunStatus.FAILED)
    with patch("pdd_agent.failure_sequential.stuck.TaskRunStore") as store_cls:
        store_cls.return_value.load.return_value = record
        stuck = detect_stuck_stages(job)
    assert len(stuck) == 1
    assert "failed" in stuck[0].reason


def test_reset_stuck_jobs_patches_pending():
    stuck_item = SimpleNamespace(
        job_id="job1",
        batch_id="batch1",
        merchant_code="BD023A",
        account_name="兔兔潮玩屋",
        updated_at="2026-06-30T10:46:03",
        stuck_stages=(SimpleNamespace(stage="listing", label="上架", run_id="", reason="x"),),
        to_dict=lambda: {
            "job_id": "job1",
            "batch_id": "batch1",
            "merchant_code": "BD023A",
            "account_name": "兔兔潮玩屋",
            "updated_at": "2026-06-30T10:46:03",
            "stuck_stages": [{"stage": "listing", "label": "上架", "run_id": "", "reason": "x"}],
        },
    )
    job = _job(listing_status=STAGE_RUNNING, listing_run_id="")
    with patch("pdd_agent.failure_sequential.stuck.list_stuck_jobs", return_value=[stuck_item]):
        with patch("pdd_agent.failure_sequential.stuck.get_job", return_value=job):
            with patch("pdd_agent.failure_sequential.stuck.patch_job") as patch_job:
                reset = reset_stuck_jobs()
    assert len(reset) == 1
    patch_job.assert_called_once()
    assert patch_job.call_args.args[0] == "job1"
    kwargs = patch_job.call_args.kwargs
    assert kwargs["listing_status"] == STAGE_PENDING
    assert kwargs["listing_run_id"] == ""
    assert kwargs["current_phase"] == "listing"

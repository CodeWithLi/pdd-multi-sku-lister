from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from pdd_agent.api.services.pipeline_service import build_listing_unit_statuses
from pdd_agent.domain.enums import RunStatus


def test_build_listing_unit_statuses_keeps_prior_batch_results(monkeypatch):
    """分批上架换 run 后，已完成批次仍显示已上架。"""
    row = SimpleNamespace(
        product_codes=[
            "BD014/第一套图/BD014A",
            "BD021/第一套图/BD021A",
        ],
        listing_run_id="run-batch-2",
        meta={
            "listing_skip_selectors": [],
            "listing_throttle": {
                "enabled": True,
                "batch_index": 1,
                "batches": [
                    ["BD014/第一套图/BD014A"],
                    ["BD021/第一套图/BD021A"],
                ],
                "unit_results_by_label": {
                    "BD014A/第一套图": {
                        "listing_label": "BD014A/第一套图",
                        "status": "success",
                        "pdd_product_id": "111",
                    }
                },
            },
        },
    )
    record = SimpleNamespace(
        status=RunStatus.RUNNING,
        phase=MagicMock(value="browser"),
        result={
            "preflight": {
                "units": [{"product_code": "BD021A", "image_set": "第一套图"}],
                "issues": [],
            },
            "results": [],
        },
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_service.TaskRunStore",
        lambda: MagicMock(load=lambda _id: record),
    )

    statuses = build_listing_unit_statuses(row)
    by_label = {item["listing_label"]: item for item in statuses}

    assert by_label["BD014A/第一套图"]["status"] == "success"
    assert by_label["BD021A/第一套图"]["status"] == "listing"


def test_build_listing_unit_statuses_marks_preflight_and_success(monkeypatch):
    row = SimpleNamespace(
        product_codes=["BD025/第一套图/BD025A", "BD030/第一套图/BD030A"],
        listing_run_id="run-1",
        meta={"listing_skip_selectors": []},
    )
    record = SimpleNamespace(
        status=RunStatus.SUCCESS,
        phase=MagicMock(value="report"),
        result={
            "preflight": {
                "units": [
                    {"product_code": "BD025A", "image_set": "第一套图"},
                    {"product_code": "BD030A", "image_set": "第一套图"},
                ],
                "issues": [
                    {
                        "level": "error",
                        "listing_label": "BD030A/第一套图",
                        "reason_code": "feishu_product_catalog_missing",
                    }
                ],
            },
            "results": [
                {
                    "listing_label": "BD025A/第一套图",
                    "status": "success",
                    "pdd_product_id": "123",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_service.TaskRunStore",
        lambda: MagicMock(load=lambda _id: record),
    )

    statuses = build_listing_unit_statuses(row)
    by_label = {item["listing_label"]: item for item in statuses}

    assert by_label["BD025A/第一套图"]["status"] == "success"
    assert by_label["BD030A/第一套图"]["status"] == "preflight_failed"
    assert by_label["BD030A/第一套图"]["reason_code"] == "feishu_product_catalog_missing"

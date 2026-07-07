"""build_listing_unit_statuses 与结果索引模块集成。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.pipeline_service import build_listing_unit_statuses
from pdd_agent.domain.enums import RunStatus


def test_build_listing_unit_statuses_resolves_three_part_skip_result():
    row = SimpleNamespace(
        pipeline_id="pipe-1",
        product_codes=["BD757/第一套图/BD757A"],
        listing_run_id="run-1",
        meta={"listing_throttle": {"enabled": True, "batch_run_ids": ["run-1"]}},
    )
    record = SimpleNamespace(
        status=RunStatus.FAILED,
        phase="report",
        result={
            "results": [
                {
                    "listing_label": "BD757/第一套图/BD757A",
                    "status": "skipped",
                    "reason": "platform_not_applicable",
                }
            ]
        },
    )

    with patch("pdd_agent.api.services.pipeline_service.TaskRunStore") as mock_store:
        mock_store.return_value.load.return_value = record
        statuses = build_listing_unit_statuses(row)

    assert len(statuses) == 1
    assert statuses[0]["listing_label"] == "BD757A/第一套图"
    assert statuses[0]["status"] == "platform_skip_dedupe"
    assert statuses[0]["reason_code"] == "platform_not_applicable"

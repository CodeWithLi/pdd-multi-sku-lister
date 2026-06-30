"""单单元失败即时飞书日志。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from pdd_agent.domain.models import ListingUnit
from pdd_agent.skills.listing.listing_unit_feishu_log import (
    schedule_listing_unit_failure_to_feishu,
)


def _sample_unit() -> ListingUnit:
    return ListingUnit(
        product_code="AXBD001A",
        image_set="第一套图",
        root=Path("."),
        carousel_images=[],
        detail_images=[],
        material_image=None,
        skus=[],
    )


def test_schedule_listing_unit_failure_to_feishu_marks_logged():
    unit = _sample_unit()
    item = {
        "status": "retryable",
        "reason": "category_next_step_no_advance",
        "error": "点击下一步后页面未跳转",
        "retryable": True,
    }
    cfg = MagicMock()
    cfg.pdd_upload_log.failure_log_enabled = True

    with patch(
        "pdd_agent.integrations.feishu.config.load_feishu_config",
        return_value=cfg,
    ), patch(
        "pdd_agent.integrations.feishu.pdd_upload_sync.schedule_pdd_upload_failure_log",
    ) as mock_schedule, patch(
        "pdd_agent.api.services.task_runner._account_display_name",
        return_value="多多李子2601",
    ), patch(
        "pdd_agent.api.services.task_runner._listing_run_timing",
        return_value=(None, None),
    ):
        ok = schedule_listing_unit_failure_to_feishu(
            "store_A",
            unit,
            item,
            run_id="run_1",
        )

    assert ok is True
    assert item.get("feishu_failure_logged") is True
    mock_schedule.assert_called_once()


def test_schedule_listing_unit_failure_skips_success():
    unit = _sample_unit()
    item = {"status": "success"}
    assert schedule_listing_unit_failure_to_feishu("store_A", unit, item) is False

"""批量整合链路 — 店铺串行启动。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_service import start_integrated_pipeline_batch


def test_batch_store_sequential_does_not_duplicate_activity_kwargs():
    captured: dict = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return {
            "pipeline_id": "pipe-1",
            "account_id": kwargs["account_id"],
            "listing_run_id": "run-1",
        }

    with patch(
        "pdd_agent.api.services.pipeline_service.start_integrated_pipeline",
        side_effect=fake_start,
    ), patch(
        "pdd_agent.api.services.pipeline_service.get_integrated_pipeline",
        return_value=MagicMock(meta={}),
    ), patch(
        "pdd_agent.api.services.pipeline_service.update_integrated_pipeline",
    ):
        result = start_integrated_pipeline_batch(
            items=[
                {"account_id": "store_A", "product_codes": ["BD001/第一套/BD001A"]},
                {"account_id": "store_B", "product_codes": ["BD002/第一套/BD002A"]},
            ],
            activity_ids=["20981"],
            store_sequential_enabled=True,
        )

    assert result["store_sequential_enabled"] is True
    assert captured["activity_id"] == "20981"
    assert captured["activity_ids"] == ["20981"]
    assert captured["account_id"] == "store_A"

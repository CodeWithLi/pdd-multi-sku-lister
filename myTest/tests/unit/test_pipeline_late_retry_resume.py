from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_late_retry_resume import (
    build_late_retry_resume_plan,
    merge_resumed_late_retry_result,
)


def _pipeline_row(**overrides):
    meta = {
        "pipeline_late_retry": {
            "listing_run_id": "lr_1",
            "succeeded_selectors": ["BD032A樱桃蛋糕笔袋/第一套图"],
        }
    }
    meta.update(overrides.pop("meta", {}) or {})
    return SimpleNamespace(
        pipeline_id="pipe_1",
        meta=meta,
        **overrides,
    )


@patch("pdd_agent.api.services.pipeline_late_retry_resume.TaskRunStore")
@patch("pdd_agent.api.services.pipeline_late_retry_resume.get_integrated_pipeline")
def test_build_plan_skips_already_succeeded_selectors(mock_get_pipeline, mock_store_cls):
    mock_get_pipeline.return_value = _pipeline_row()
    store = MagicMock()
    store.load.return_value = SimpleNamespace(
        result={
            "results": [
                {
                    "listing_label": "BD045A/第一套图",
                    "status": "success",
                    "pdd_product_id": "1001",
                }
            ]
        }
    )
    mock_store_cls.return_value = store

    with patch(
        "pdd_agent.api.services.pipeline_late_retry_resume._selector_to_label",
        side_effect=lambda selector: selector,
    ):
        plan = build_late_retry_resume_plan(
            pipeline_id="pipe_1",
            run_id="lr_1",
            requested_selectors=[
                "BD032A樱桃蛋糕笔袋/第一套图",
                "BD045A/第一套图",
                "BD070A/第一套图",
            ],
        )

    assert plan is not None
    assert plan.to_run_selectors == ["BD070A/第一套图"]
    assert set(plan.succeeded_selectors) == {
        "BD032A樱桃蛋糕笔袋/第一套图",
        "BD045A/第一套图",
    }


def test_merge_resumed_late_retry_result_keeps_prior_success_items():
    plan = SimpleNamespace(
        prior_success_result_items=[
            {
                "listing_label": "BD032A樱桃蛋糕笔袋/第一套图",
                "status": "success",
                "pdd_product_id": "1001",
            }
        ],
        to_run_selectors=["BD070A/第一套图"],
        summary=lambda: {"requested": 2, "already_succeeded": 1, "to_run": 1},
    )
    result = merge_resumed_late_retry_result(
        plan,
        {
            "results": [
                {
                    "listing_label": "BD070A/第一套图",
                    "status": "failed",
                    "reason": "negative_inventory_skip",
                }
            ]
        },
    )

    labels = [item.get("listing_label") for item in result["results"]]
    assert labels == ["BD032A樱桃蛋糕笔袋/第一套图", "BD070A/第一套图"]
    assert result["late_retry_resume"]["already_succeeded"] == 1

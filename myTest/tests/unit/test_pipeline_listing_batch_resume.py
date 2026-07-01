"""分批上架批内续跑。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_listing_batch_resume import (
    BatchUnitOutcome,
    build_batch_resume_plan,
    classify_listing_unit_outcome,
    merge_listing_result_items,
    merge_resumed_listing_graph_result,
    prepare_listing_batch_resume,
)


def _pipeline_row(*, batch_index: int = 0, batch_progress: dict | None = None):
    selectors = [f"BD{i:03d}/第一套图/BD{i:03d}A" for i in range(1, 11)]
    batches = [selectors]
    meta = {
        "listing_throttle": {
            "enabled": True,
            "batch_index": batch_index,
            "total_batches": 14,
            "batches": batches,
            "unit_results_by_label": {},
            "batch_progress": batch_progress or {},
        }
    }
    return SimpleNamespace(pipeline_id="pipe-1", meta=meta, listing_run_id="run-1")


def test_classify_success_and_failed():
    assert classify_listing_unit_outcome({"status": "success", "pdd_product_id": "1"}) == BatchUnitOutcome.SUCCESS
    assert classify_listing_unit_outcome({"status": "failed", "reason": "x"}) == BatchUnitOutcome.FAILED
    assert classify_listing_unit_outcome(None) == BatchUnitOutcome.PENDING


def test_build_plan_skips_success_runs_only_failed_and_pending():
    row = _pipeline_row()
    run_results = {
        "BD001A/第一套图": {"listing_label": "BD001A/第一套图", "status": "failed", "reason": "a"},
        "BD002A/第一套图": {"listing_label": "BD002A/第一套图", "status": "failed", "reason": "b"},
        "BD003A/第一套图": {"listing_label": "BD003A/第一套图", "status": "success", "pdd_product_id": "9"},
    }
    with patch(
        "pdd_agent.api.services.pipeline_listing_batch_resume.get_integrated_pipeline",
        return_value=row,
    ), patch(
        "pdd_agent.api.services.pipeline_listing_batch_resume._load_results_by_label_from_run",
        return_value=run_results,
    ):
        plan = build_batch_resume_plan(
            pipeline_id="pipe-1",
            run_id="run-1",
            requested_codes=row.meta["listing_throttle"]["batches"][0],
        )

    assert plan is not None
    assert plan.batch_size == 10
    assert len(plan.success) == 1
    assert len(plan.failed) == 2
    assert len(plan.pending) == 7
    assert len(plan.to_run_selectors) == 9
    assert len(plan.success) + len(plan.failed) + len(plan.pending) == 10


def test_prepare_returns_only_to_run_selectors():
    row = _pipeline_row()
    selectors = row.meta["listing_throttle"]["batches"][0]
    run_results = {
        "BD001A/第一套图": {"listing_label": "BD001A/第一套图", "status": "failed"},
        "BD002A/第一套图": {"listing_label": "BD002A/第一套图", "status": "success", "pdd_product_id": "1"},
    }
    with patch(
        "pdd_agent.api.services.pipeline_listing_batch_resume.get_integrated_pipeline",
        return_value=row,
    ), patch(
        "pdd_agent.api.services.pipeline_listing_batch_resume._load_results_by_label_from_run",
        return_value=run_results,
    ):
        to_run, plan = prepare_listing_batch_resume(
            pipeline_id="pipe-1",
            run_id="run-1",
            product_codes=selectors,
        )

    assert plan is not None
    assert len(to_run) == 9
    assert "BD002/第一套图/BD002A" not in to_run
    assert "BD001/第一套图/BD001A" in to_run


def test_merge_graph_result_keeps_prior_success():
    from pdd_agent.api.services.pipeline_listing_batch_resume import BatchResumePlan, BatchUnitSlot

    plan = BatchResumePlan(
        pipeline_id="pipe-1",
        batch_index=0,
        batch_size=2,
        prior_result_items=[
            {"listing_label": "A/第一套图", "status": "success", "pdd_product_id": "1"},
        ],
    )
    merged = merge_resumed_listing_graph_result(
        plan,
        {"results": [{"listing_label": "B/第一套图", "status": "failed", "reason": "x"}]},
    )
    labels = {item["listing_label"] for item in merged["results"]}
    assert labels == {"A/第一套图", "B/第一套图"}


def test_merge_listing_result_items_new_overrides_old():
    prior = [{"listing_label": "X/第一套图", "status": "failed"}]
    new = [{"listing_label": "X/第一套图", "status": "success", "pdd_product_id": "9"}]
    merged = merge_listing_result_items(prior, new)
    assert merged[0]["status"] == "success"


def test_non_throttled_pipeline_returns_none():
    row = SimpleNamespace(pipeline_id="pipe-2", meta={}, listing_run_id="run-2")
    with patch(
        "pdd_agent.api.services.pipeline_listing_batch_resume.get_integrated_pipeline",
        return_value=row,
    ):
        codes, plan = prepare_listing_batch_resume(
            pipeline_id="pipe-2",
            run_id="run-2",
            product_codes=["A"],
        )
    assert plan is None
    assert codes == ["A"]

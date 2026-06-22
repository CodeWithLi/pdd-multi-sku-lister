from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pdd_agent.agents.listing.graph import should_continue_after_preflight
from pdd_agent.api.services import task_runner
from pdd_agent.api.services.pipeline_service import _listing_failure_meta
from pdd_agent.domain.enums import RunStatus
from pdd_agent.domain.models import ListingUnit, PreflightIssue, PreflightReport
from pdd_agent.skills.listing import upload as listing_upload


def _unit(code: str, image_set: str) -> ListingUnit:
    return ListingUnit(
        product_code=code,
        family_code=code[:5],
        image_set=image_set,
        root=Path("."),
    )


def test_should_continue_after_preflight_with_partial_errors():
    report = PreflightReport(
        units=[_unit("BD722A", "第一套图"), _unit("BD722B", "第一套图")],
        issues=[
            PreflightIssue(level="error", message="BD722A商品表没数据", listing_label="BD722A/第一套图"),
        ],
    )
    state = {"preflight": report, "dry_run": False}
    assert should_continue_after_preflight(state) == "browser"
    assert len(report.valid_units) == 1


def test_should_continue_after_preflight_stops_when_no_valid_units():
    report = PreflightReport(
        units=[_unit("BD722A", "第一套图")],
        issues=[
            PreflightIssue(level="error", message="无有效 SKU", listing_label="BD722A/第一套图"),
        ],
    )
    state = {"preflight": report, "dry_run": False}
    assert should_continue_after_preflight(state) == "report"


def test_run_listing_uploads_continues_after_first_failure(monkeypatch):
    units = [_unit("BD722A", "第一套图"), _unit("BD722B", "第一套图")]
    calls: list[str] = []

    def fake_upload(page, account_id, unit, *args, **kwargs):
        calls.append(unit.listing_label)
        if unit.product_code == "BD722A":
            return {
                "status": "failed",
                "reason": "rejected_after_publish",
                "error": "平台已驳回",
                "listing_label": unit.listing_label,
            }
        return {
            "status": "success",
            "pdd_product_id": "123",
            "listing_label": unit.listing_label,
        }

    monkeypatch.setattr(listing_upload, "upload_one_listing", fake_upload)
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    results = listing_upload.run_listing_uploads(
        page=MagicMock(),
        account_id="store_A",
        units=units,
    )

    assert calls == ["BD722A/第一套图", "BD722B/第一套图"]
    assert len(results) == 2
    assert results[0]["status"] == "failed"
    assert results[1]["status"] == "success"


def test_resolve_listing_run_status_partial_success():
    result = {
        "results": [
            {"status": "failed", "listing_label": "BD722A/第一套图"},
            {"status": "success", "pdd_product_id": "999", "listing_label": "BD722B/第一套图"},
        ]
    }
    assert task_runner._resolve_listing_run_status(result) == RunStatus.SUCCESS


def test_resolve_listing_run_status_all_failed():
    result = {
        "results": [
            {"status": "failed", "listing_label": "BD722A/第一套图"},
        ],
        "errors": ["preflight issue"],
    }
    assert task_runner._resolve_listing_run_status(result) == RunStatus.FAILED


def test_listing_failure_meta_collects_preflight_and_upload_failures():
    meta = _listing_failure_meta(
        {
            "preflight": {
                "issues": [
                    {"level": "error", "listing_label": "BD022A/第一套图", "message": "没数据"},
                ]
            },
            "results": [
                {"status": "success", "pdd_product_id": "1", "listing_label": "BD023A/第一套图"},
                {"status": "failed", "listing_label": "BD024A/第一套图", "error": "超时"},
            ],
        }
    )
    assert meta["listing_outcome"] == "partial_listing_failure"
    assert meta["listing_failed_count"] == 2
    assert "BD022A/第一套图" in meta["listing_failed_labels"]
    assert "BD024A/第一套图" in meta["listing_failed_labels"]

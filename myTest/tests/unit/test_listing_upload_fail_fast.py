from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pdd_agent.domain.models import ListingUnit
from pdd_agent.skills.listing import upload as listing_upload


def _unit(code: str, image_set: str) -> ListingUnit:
    return ListingUnit(
        product_code=code,
        family_code=code[:5],
        image_set=image_set,
        root=Path("."),
    )


def test_run_listing_uploads_stops_after_manual_cancel(monkeypatch):
    units = [_unit("BD722A", "第一套图"), _unit("BD722B", "第一套图")]
    calls: list[str] = []

    def fake_upload(page, account_id, unit, *args, **kwargs):
        calls.append(unit.listing_label)
        return {
            "status": "success",
            "pdd_product_id": "123",
            "listing_label": unit.listing_label,
        }

    def fake_is_cancelled(run_id: str) -> bool:
        return run_id == "run-cancel" and len(calls) >= 1

    monkeypatch.setattr(listing_upload, "upload_one_listing", fake_upload)
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))
    monkeypatch.setattr("pdd_agent.api.services.run_cancel.is_cancelled", fake_is_cancelled)

    results = listing_upload.run_listing_uploads(
        page=MagicMock(),
        account_id="store_A",
        units=units,
        run_id="run-cancel",
    )

    assert calls == ["BD722A/第一套图"]
    assert len(results) == 1


def test_run_listing_uploads_runs_all_when_everything_succeeds(monkeypatch):
    units = [_unit("BD722A", "第一套图"), _unit("BD722B", "第一套图")]
    calls: list[str] = []

    def fake_upload(page, account_id, unit, *args, **kwargs):
        calls.append(unit.listing_label)
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


def test_listing_unit_succeeded():
    assert listing_upload._listing_unit_succeeded({"status": "success", "pdd_product_id": "1"})
    assert listing_upload._listing_unit_succeeded({"status": "listed"})
    assert not listing_upload._listing_unit_succeeded({"status": "failed"})
    assert not listing_upload._listing_unit_succeeded({"status": "retryable", "retryable": True})

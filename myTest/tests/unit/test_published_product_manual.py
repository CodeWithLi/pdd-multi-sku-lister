import pytest
from fastapi import HTTPException

from pdd_agent.api.services import published_product_service as svc


def test_normalize_pdd_product_id():
    assert svc._normalize_pdd_product_id(" 965836045952 ") == "965836045952"
    assert svc._normalize_pdd_product_id("ID:965836045952") == "965836045952"


def test_create_manual_requires_account(monkeypatch):
    monkeypatch.setattr(svc, "is_database_available", lambda: True)
    with pytest.raises(HTTPException) as exc:
        svc.create_manual_published_product(
            account_id="",
            pdd_product_id="123",
            product_code="BD716A",
            listing_label="test",
        )
    assert exc.value.status_code == 422


def test_create_manual_requires_numeric_pdd_id(monkeypatch):
    monkeypatch.setattr(svc, "is_database_available", lambda: True)
    monkeypatch.setattr(svc, "get_account_or_none", lambda account_id: object())
    with pytest.raises(HTTPException) as exc:
        svc.create_manual_published_product(
            account_id="store_A",
            pdd_product_id="abc",
            product_code="BD716A",
            listing_label="test",
        )
    assert exc.value.status_code == 422
    assert "数字" in str(exc.value.detail)


def test_create_manual_unknown_account(monkeypatch):
    monkeypatch.setattr(svc, "is_database_available", lambda: True)
    monkeypatch.setattr(svc, "get_account_or_none", lambda account_id: None)
    with pytest.raises(HTTPException) as exc:
        svc.create_manual_published_product(
            account_id="missing",
            pdd_product_id="965836045952",
            product_code="BD716A",
            listing_label="test",
        )
    assert exc.value.status_code == 422


def test_create_manual_pdd_id_conflict(monkeypatch):
    class FakeRow:
        mapping_id = "existing_map"
        product_code = "BD046A"
        image_set = "第一套"

    monkeypatch.setattr(svc, "is_database_available", lambda: True)
    monkeypatch.setattr(svc, "get_account_or_none", lambda account_id: object())
    monkeypatch.setattr(
        svc,
        "get_published_products_by_pdd_product_ids",
        lambda **kwargs: [FakeRow()],
    )
    with pytest.raises(HTTPException) as exc:
        svc.create_manual_published_product(
            account_id="store_A",
            pdd_product_id="965836045952",
            product_code="BD716A",
            listing_label="test",
        )
    assert exc.value.status_code == 409

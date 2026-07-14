"""listing_published_product 单元测试。"""

from dy_agent.skills.listing.listing_published_product import (
    normalize_platform_status,
    parse_listed_at,
    persist_listed_product_item,
)
from dy_agent.domain.models import ListingUnit
from pathlib import Path


def test_parse_listed_at_slash_format():
    dt = parse_listed_at("2026/07/13 10:27:44")
    assert dt is not None
    assert dt.year == 2026
    assert dt.hour == 10


def test_parse_listed_at_iso_format():
    dt = parse_listed_at("2026-07-13T10:27:44")
    assert dt is not None
    assert dt.minute == 27


def test_normalize_platform_status():
    assert normalize_platform_status("售卖中") == "on_sale"
    assert normalize_platform_status("审核中") == "pending_review"


def test_persist_listed_product_item_skips_non_success():
    unit = ListingUnit(product_code="BD071A", root=Path("."))
    assert persist_listed_product_item("run1", "shop1", unit, {"status": "step5_done"}) is None


def test_persist_listed_product_item_skips_missing_product_id():
    unit = ListingUnit(product_code="BD071A", root=Path("."))
    assert persist_listed_product_item(
        "run1",
        "shop1",
        unit,
        {"status": "success", "listing_label": "BD071A/第一套"},
    ) is None

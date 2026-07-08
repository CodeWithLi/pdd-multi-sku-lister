"""inventory_delist.audit 单元测试。"""

from pdd_agent.inventory_delist.audit import _resolve_delist_status
from pdd_agent.inventory_delist.published_query import OnSalePublishedItem


def _item() -> OnSalePublishedItem:
    return OnSalePublishedItem(
        mapping_id="map1",
        account_id="acc1",
        product_code="BD070A",
        family_code="BD070",
        image_set="A",
        merchant_code="BD070A",
        pdd_product_id="123",
        selector="BD070/A/BD070A",
        status="on_sale",
    )


def test_resolve_completed_when_deleted():
    status, _ = _resolve_delist_status(
        account_success=True,
        account_error="",
        dry_run=False,
        published_item=_item(),
        result_items=[{"status": "delisted", "merchant_code": "BD070A"}],
        deleted_mapping_ids={"map1"},
    )
    assert status == "completed"


def test_resolve_dry_run():
    status, message = _resolve_delist_status(
        account_success=True,
        account_error="",
        dry_run=True,
        published_item=_item(),
        result_items=[{"status": "delisted", "merchant_code": "BD070A"}],
        deleted_mapping_ids=set(),
    )
    assert status == "dry_run"
    assert "dry_run" in message


def test_resolve_failed_account():
    status, message = _resolve_delist_status(
        account_success=False,
        account_error="浏览器失败",
        dry_run=False,
        published_item=_item(),
        result_items=[],
        deleted_mapping_ids=set(),
    )
    assert status == "failed"
    assert message == "浏览器失败"

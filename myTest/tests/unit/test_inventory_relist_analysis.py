"""inventory relist analysis 单元测试。"""

from unittest.mock import MagicMock, patch

from pdd_agent.inventory_delist.relist_analysis import analyze_inventory_relist_targets


def _mock_row(**kwargs):
    row = MagicMock()
    row.record_id = kwargs.get("record_id", "r1")
    row.account_id = kwargs.get("account_id", "acc1")
    row.shop_display_name = kwargs.get("shop_display_name", "店A")
    row.product_code = kwargs.get("product_code", "BD070A")
    row.merchant_code = kwargs.get("merchant_code", "BD070A")
    row.mapping_id = kwargs.get("mapping_id", "m1")
    row.pdd_product_id = kwargs.get("pdd_product_id", "123")
    row.erp_available_qty = kwargs.get("erp_available_qty", -2)
    row.is_common_on_sale = kwargs.get("is_common_on_sale", False)
    row.delisted_at = kwargs.get("delisted_at")
    return row


@patch("pdd_agent.db.session.is_database_available", return_value=True)
@patch("pdd_agent.inventory_delist.relist_analysis.load_jushuitan_inventory_map")
@patch("pdd_agent.inventory_delist.relist_analysis.list_pending_relist_records")
def test_relist_multi_shop_linkage(mock_list, mock_feishu, _db):
    mock_list.return_value = [
        _mock_row(record_id="r1", account_id="acc1", shop_display_name="店A", is_common_on_sale=True),
        _mock_row(record_id="r2", account_id="acc2", shop_display_name="店B", is_common_on_sale=True),
        _mock_row(record_id="r3", account_id="acc3", shop_display_name="店C", is_common_on_sale=True),
    ]
    mock_feishu.return_value = {"BD070A": 5}

    analysis = analyze_inventory_relist_targets(["acc1", "acc2", "acc3"])

    assert analysis.pending_record_count == 3
    assert analysis.common_pending_codes == ["BD070A"]
    assert len(analysis.relist_candidates) == 1
    target = analysis.relist_candidates[0]
    assert target.product_code == "BD070A"
    assert target.account_ids == ["acc1", "acc2", "acc3"]
    assert target.is_multi_shop is True
    assert target.available_qty == 5


@patch("pdd_agent.db.session.is_database_available", return_value=True)
@patch("pdd_agent.inventory_delist.relist_analysis.load_jushuitan_inventory_map")
@patch("pdd_agent.inventory_delist.relist_analysis.list_pending_relist_records")
def test_relist_still_negative(mock_list, mock_feishu, _db):
    mock_list.return_value = [_mock_row()]
    mock_feishu.return_value = {"BD070A": -1}

    analysis = analyze_inventory_relist_targets(["acc1"])

    assert not analysis.relist_candidates
    assert len(analysis.still_negative_codes) == 1
    assert analysis.still_negative_codes[0].available_qty == -1

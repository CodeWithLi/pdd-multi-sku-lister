"""库存下架分析逻辑单元测试。"""

from unittest.mock import patch

from pdd_agent.inventory_delist.analysis import analyze_inventory_delist_targets
from pdd_agent.inventory_delist.published_query import OnSalePublishedItem, PublishedCountSnapshot


def _item(account_id: str, code: str) -> OnSalePublishedItem:
    return OnSalePublishedItem(
        mapping_id=f"m-{code}",
        account_id=account_id,
        product_code=code,
        family_code="F",
        image_set="S",
        merchant_code=code,
        pdd_product_id="pid",
        selector=f"F/S/{code}",
        status="on_sale",
    )


def _counts(on_sale: int, total: int = 0) -> PublishedCountSnapshot:
    total = total or on_sale
    return PublishedCountSnapshot(
        account_id="x",
        total_rows=total,
        on_sale_rows=on_sale,
        delisted_rows=0,
        other_status_rows=max(0, total - on_sale),
    )


def test_analyze_common_exclusive_and_negative_inventory():
    with (
        patch(
            "pdd_agent.inventory_delist.analysis.list_on_sale_items",
            side_effect=lambda aid, **_: {
                "shop-a": [_item("shop-a", "CODE1"), _item("shop-a", "CODE2"), _item("shop-a", "CODE3")],
                "shop-b": [_item("shop-b", "CODE1"), _item("shop-b", "CODE4")],
            }.get(aid, []),
        ),
        patch(
            "pdd_agent.inventory_delist.analysis.count_published_by_account",
            return_value=_counts(3),
        ),
        patch(
            "pdd_agent.inventory_delist.analysis.load_jushuitan_inventory_map",
            return_value={
                "CODE1": 5,
                "CODE2": -1,
                "CODE3": 0,
                "CODE4": -3,
            },
        ),
    ):
        result = analyze_inventory_delist_targets(["shop-a", "shop-b"], force_feishu_refresh=True)

    assert result.common_on_sale_codes == ["CODE1"]
    assert result.negative_inventory_codes == ["CODE2", "CODE4"]
    assert result.feishu_called is True
    by_account = {row.account_id: row for row in result.per_account}
    assert by_account["shop-a"].exclusive_codes == ["CODE2", "CODE3"]
    assert by_account["shop-b"].exclusive_codes == ["CODE4"]
    assert by_account["shop-a"].delist_candidate_codes == ["CODE2"]
    assert by_account["shop-b"].delist_candidate_codes == ["CODE4"]


def test_analyze_empty_accounts():
    result = analyze_inventory_delist_targets([])
    assert result.account_ids == []
    assert result.common_on_sale_codes == []
    assert result.negative_inventory_codes == []
    assert result.feishu_called is False


def test_analyze_skips_feishu_when_no_on_sale_products():
    with patch(
        "pdd_agent.inventory_delist.analysis.list_on_sale_items",
        return_value=[],
    ), patch(
        "pdd_agent.inventory_delist.analysis.count_published_by_account",
        return_value=_counts(0),
    ), patch(
        "pdd_agent.inventory_delist.analysis.load_jushuitan_inventory_map",
    ) as feishu_mock:
        result = analyze_inventory_delist_targets(["shop-a"])
    assert result.feishu_called is False
    feishu_mock.assert_not_called()
    assert "跳过飞书" in result.diagnostics.get("message", "")

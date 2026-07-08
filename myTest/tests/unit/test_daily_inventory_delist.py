"""负库存下架每日统计单元测试。"""

from datetime import date, datetime
from unittest.mock import MagicMock

from pdd_agent.api.routes import daily_inventory_delist as route_module


def test_summarize_daily_inventory_delist(monkeypatch):
    target = date(2026, 7, 8)

    monkeypatch.setattr(route_module, "is_database_available", lambda: True)
    monkeypatch.setattr(
        route_module,
        "summarize_daily_inventory_delist_records",
        lambda **kwargs: [{"account_id": "acc1", "shop_display_name": "兔兔潮玩屋", "count": 2}],
    )
    monkeypatch.setattr(
        route_module,
        "summarize_daily_inventory_relist_records",
        lambda **kwargs: [{"account_id": "acc1", "shop_display_name": "兔兔潮玩屋", "count": 1}],
    )
    monkeypatch.setattr(route_module, "count_daily_inventory_delist_records", lambda **kwargs: 2)
    monkeypatch.setattr(route_module, "count_daily_inventory_relist_records", lambda **kwargs: 1)

    result = route_module.summarize_daily_inventory_delist("2026-07-08")
    assert result.stat_date == target
    assert result.delist_total == 2
    assert result.relist_total == 1
    assert result.delist_by_shop[0].count == 2


def test_list_daily_inventory_delist_items_relist(monkeypatch):
    row = MagicMock()
    row.record_id = "rec1"
    row.account_id = "acc1"
    row.shop_display_name = "兔兔潮玩屋"
    row.product_code = "BD070B"
    row.merchant_code = "BD070B"
    row.pdd_product_id = "123"
    row.erp_available_qty = 5
    row.delist_status = "completed"
    row.message = "已重新上架"
    row.is_relisted = True
    row.delisted_at = datetime(2026, 7, 8, 10, 0, 0)
    row.relisted_at = datetime(2026, 7, 8, 15, 0, 0)
    row.trigger = "manual"

    monkeypatch.setattr(route_module, "is_database_available", lambda: True)
    monkeypatch.setattr(route_module, "get_account_or_none", lambda _aid: object())
    monkeypatch.setattr(route_module, "list_daily_inventory_relist_records", lambda **kwargs: [row])
    monkeypatch.setattr(route_module, "count_daily_inventory_relist_records", lambda **kwargs: 1)

    result = route_module.list_daily_inventory_delist_items(
        stat_date="2026-07-08",
        action="relist",
        account_id="acc1",
        limit=50,
    )
    assert result.action == "relist"
    assert result.total == 1
    assert result.items[0].product_code == "BD070B"

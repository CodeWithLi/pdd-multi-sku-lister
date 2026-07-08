"""库存下架 account_resolver 单元测试。"""

from unittest.mock import patch

from pdd_agent.inventory_delist.account_resolver import resolve_enabled_account_ids


def _mock_accounts():
    return [
        type("A", (), {"account_id": "store_A", "username": "多多李子2601", "enabled": True})(),
        type("A", (), {"account_id": "多多李子2602", "enabled": True})(),
    ]


def test_resolve_uses_db_account_list():
    with patch(
        "pdd_agent.inventory_delist.account_resolver.list_account_configs",
        return_value=_mock_accounts(),
    ), patch(
        "pdd_agent.inventory_delist.account_resolver.get_cached_shop_display_name",
        side_effect=lambda aid: "兔兔潮玩屋" if aid == "store_A" else "",
    ), patch(
        "pdd_agent.inventory_delist.account_resolver.resolve_account_display_name",
        side_effect=lambda aid: "兔兔潮玩屋" if aid == "store_A" else aid,
    ), patch(
        "pdd_agent.inventory_delist.account_resolver.list_account_ids_by_display_name",
        return_value=[],
    ):
        resolved, rejected = resolve_enabled_account_ids(["store_A", "invalid"])
    assert resolved == ["store_A"]
    assert rejected == ["invalid"]


def test_resolve_username_and_shop_display_name():
    with patch(
        "pdd_agent.inventory_delist.account_resolver.list_account_configs",
        return_value=_mock_accounts(),
    ), patch(
        "pdd_agent.inventory_delist.account_resolver.get_cached_shop_display_name",
        side_effect=lambda aid: "兔兔潮玩屋" if aid == "store_A" else "",
    ), patch(
        "pdd_agent.inventory_delist.account_resolver.resolve_account_display_name",
        side_effect=lambda aid: "兔兔潮玩屋" if aid == "store_A" else aid,
    ), patch(
        "pdd_agent.inventory_delist.account_resolver.list_account_ids_by_display_name",
        side_effect=lambda name: ["store_A"] if name == "兔兔潮玩屋" else [],
    ):
        by_username, rejected_u = resolve_enabled_account_ids(["多多李子2601"])
        by_shop, rejected_s = resolve_enabled_account_ids(["兔兔潮玩屋"])
    assert by_username == ["store_A"]
    assert rejected_u == []
    assert by_shop == ["store_A"]
    assert rejected_s == []

"""库存下架 account_resolver 单元测试。"""

from unittest.mock import patch

from pdd_agent.inventory_delist.account_resolver import resolve_enabled_account_ids


def test_resolve_uses_db_account_list():
    with patch(
        "pdd_agent.inventory_delist.account_resolver.list_account_configs",
        return_value=[
            type("A", (), {"account_id": "多多李子2601", "enabled": True})(),
            type("A", (), {"account_id": "多多李子2602", "enabled": True})(),
        ],
    ):
        resolved, rejected = resolve_enabled_account_ids(["多多李子2601", "invalid"])
    assert resolved == ["多多李子2601"]
    assert rejected == ["invalid"]

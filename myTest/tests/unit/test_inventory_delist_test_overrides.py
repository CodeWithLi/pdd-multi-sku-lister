"""库存下架 test_overrides 单元测试。"""

from pdd_agent.inventory_delist.test_overrides import (
    apply_test_inventory_overrides,
    parse_test_inventory_overrides,
)


def test_parse_and_apply_override_after_feishu():
    overrides = parse_test_inventory_overrides(
        enabled=True,
        text="BD022A\nBD070A,-3",
    )
    assert overrides["BD022A"] == -1
    assert overrides["BD070A"] == -3

    merged, applied = apply_test_inventory_overrides(
        {"BD022A": 3416, "BD070A": 11703},
        overrides,
    )
    assert merged["BD022A"] == -1
    assert merged["BD070A"] == -3
    assert applied[0]["original_qty"] == 3416
    assert applied[0]["feishu_had_record"] is True


def test_apply_override_injects_when_feishu_missing():
    merged, applied = apply_test_inventory_overrides(
        {},
        {"NEWCODE": -2},
    )
    assert merged["NEWCODE"] == -2
    assert applied[0]["feishu_had_record"] is False

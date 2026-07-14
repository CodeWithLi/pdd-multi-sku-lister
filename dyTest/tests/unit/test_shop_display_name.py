"""店铺名抓取过滤单元测试。"""

from dy_agent.browser.shop_display_name import _SHOP_NAME_BLOCKLIST


def test_alliance_entry_is_blocklisted():
    assert any("精选联盟" in x for x in _SHOP_NAME_BLOCKLIST)


def test_blocklist_rejects_alliance_label():
    from dy_agent.browser.shop_display_name import is_invalid_shop_display_name

    assert is_invalid_shop_display_name("精选联盟")
    assert is_invalid_shop_display_name("精选联盟供应...")
    assert not is_invalid_shop_display_name("兔兔潮玩屋")

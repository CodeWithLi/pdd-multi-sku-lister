"""营销活动报名区搜索框定位（排除待报名商品区）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.campaign.marketing_activity_search_input_scope import (
    click_activity_search_button_scoped,
    fill_activity_search_input_scoped,
    find_activity_search_input_scoped,
    is_activity_registration_search_placeholder,
    is_pending_product_search_placeholder,
)


def test_pending_product_placeholder_rejected():
    ph = "输入商品ID搜索商品，多个ID以逗号隔开"
    assert is_pending_product_search_placeholder(ph) is True
    assert is_activity_registration_search_placeholder(ph) is False


def test_activity_registration_placeholder_accepted():
    ph = "输入活动名称或ID搜索，多个ID以逗号隔开"
    assert is_pending_product_search_placeholder(ph) is False
    assert is_activity_registration_search_placeholder(ph) is True


def test_generic_id_search_without_activity_name_rejected():
    ph = "输入ID搜索"
    assert is_activity_registration_search_placeholder(ph) is False


def test_find_scoped_input_via_js():
    page = MagicMock()
    page.run_js.return_value = {
        "found": True,
        "placeholder": "输入活动名称或ID搜索，多个ID以逗号隔开",
        "value": "",
        "section_score": 120,
        "scoped": True,
    }
    page._page = None
    out = find_activity_search_input_scoped(page)
    assert out.get("found") is True
    assert out.get("scoped") is True


def test_fill_scoped_input():
    page = MagicMock()
    page._page = None
    page.run_js.side_effect = [
        {"found": True, "value": "", "section_score": 120, "scoped": True},
        {
            "found": True,
            "filled": True,
            "value": "20981",
            "method": "scoped_react_input_setter",
            "scoped": True,
        },
        {
            "found": True,
            "placeholder": "输入活动名称或ID搜索，多个ID以逗号隔开",
            "value": "20981",
            "scoped": True,
        },
    ]
    out = fill_activity_search_input_scoped(page, "20981")
    assert out.get("filled") is True
    assert out.get("value") == "20981"


def test_click_scoped_query_button():
    page = MagicMock()
    page._page = None
    page.run_js.return_value = {"clicked": True, "text": "查询", "method": "scoped_near_input", "scoped": True}
    out = click_activity_search_button_scoped(page)
    assert out.get("clicked") is True
    assert out.get("scoped") is True

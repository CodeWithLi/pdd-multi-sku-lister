"""listing_shipping_template_priority 单元测试。"""

from pdd_agent.skills.listing import listing_shipping_template_priority as priority


def test_resolve_pick_prefers_zuixin_quanguo_when_both_present():
    options = [
        "新疆西藏收费默认模板",
        "全国最新",
        "最新全国",
    ]
    assert priority.resolve_pick_from_visible_options(options) == "最新全国"


def test_resolve_pick_falls_back_to_quanguo_zuixin():
    options = [
        "新疆西藏收费默认模板",
        "全国最新",
        "默认2025-12-19",
    ]
    assert priority.resolve_pick_from_visible_options(options) == "全国最新"


def test_resolve_pick_returns_none_when_no_match():
    options = ["新疆西藏收费默认模板", "包邮模板"]
    assert priority.resolve_pick_from_visible_options(options) is None


def test_shipping_state_matches_acceptable():
    assert priority.shipping_state_matches_acceptable("最新全国") is True
    assert priority.shipping_state_matches_acceptable("最新全网") is True
    assert priority.shipping_state_matches_acceptable("全国最新") is True
    assert priority.shipping_state_matches_acceptable("新疆西藏收费默认模板") is False


def test_resolve_matched_template_name():
    assert priority.resolve_matched_template_name("全国最新") == "全国最新"
    assert priority.resolve_matched_template_name("最新全网") == "最新全国"
    assert priority.resolve_matched_template_name("包邮模板") is None


def test_flatten_candidates_order():
    assert priority.flatten_shipping_template_candidates() == (
        "最新全国",
        "最新全网",
        "全国最新",
    )


def test_iter_selection_attempts():
    attempts = priority.iter_shipping_template_selection_attempts()
    assert attempts[0] == ("最新全国", ("最新全网",))
    assert attempts[1] == ("全国最新", ())

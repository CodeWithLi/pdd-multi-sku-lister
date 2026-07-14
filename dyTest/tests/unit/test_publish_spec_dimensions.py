"""publish_spec_dimensions 单元测试。"""

from dy_agent.skills.listing.publish_spec_dimensions import _spec_value_candidates


def test_spec_value_candidates_adds_color_suffix():
    assert _spec_value_candidates("卡其") == ["卡其", "卡其色"]


def test_spec_value_candidates_strips_color_suffix():
    assert _spec_value_candidates("卡其色") == ["卡其色", "卡其"]


def test_spec_value_candidates_empty():
    assert _spec_value_candidates("") == []

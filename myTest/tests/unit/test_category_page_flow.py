"""分类页 flow 封装测试。"""

from __future__ import annotations

from pdd_agent.skills.listing import category_page_flow as flow


def test_random_category_render_wait_is_multiple_of_five_in_range():
    for _ in range(30):
        value = flow.random_category_render_wait_seconds()
        assert value in flow.CATEGORY_RENDER_WAIT_OPTIONS
        assert 20 <= value <= 45
        assert value % 5 == 0


def test_resolve_category_render_wait_burst_vs_simple():
    assert flow.resolve_category_render_wait(burst_demo=False) == flow.DEFAULT_SIMPLE_RENDER_WAIT
    assert flow.resolve_category_render_wait(burst_demo=True) in flow.CATEGORY_RENDER_WAIT_OPTIONS

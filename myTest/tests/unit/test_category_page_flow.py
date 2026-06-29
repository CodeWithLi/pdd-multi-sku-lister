"""分类页 flow 封装测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing import category_page_flow as flow
from pdd_agent.skills.listing import upload as listing_upload


def test_random_category_render_wait_is_multiple_of_five_in_range():
    for _ in range(30):
        value = flow.random_category_render_wait_seconds()
        assert value in flow.CATEGORY_RENDER_WAIT_OPTIONS
        assert 20 <= value <= 45
        assert value % 5 == 0


def test_resolve_category_render_wait_burst_vs_simple():
    assert flow.resolve_category_render_wait(burst_demo=False) == flow.DEFAULT_SIMPLE_RENDER_WAIT
    assert flow.resolve_category_render_wait(burst_demo=True) in flow.CATEGORY_RENDER_WAIT_OPTIONS


def test_resolve_category_page_mode_branch_b_is_manual(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(listing_upload, "_category_direct_next_ready", lambda *_a, **_k: False)
    assert listing_upload._resolve_category_page_mode(page, "B") == "manual_picker"


def test_resolve_category_page_mode_branch_b_direct_next(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(listing_upload, "_category_direct_next_ready", lambda *_a, **_k: True)
    assert listing_upload._resolve_category_page_mode(page, "B") == "direct_next"


def test_resolve_category_page_mode_branch_c_manual_flag(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(listing_upload, "_category_page_is_manual_picker", lambda *_a, **_k: False)
    assert (
        listing_upload._resolve_category_page_mode(page, "C", manual_category=True)
        == "manual_picker"
    )


def test_resolve_category_page_mode_branch_c_render_wait(monkeypatch):
    page = MagicMock()
    page.ele.return_value = None
    monkeypatch.setattr(listing_upload, "_category_direct_next_ready", lambda *_a, **_k: False)
    assert listing_upload._resolve_category_page_mode(page, "C", manual_category=False) == "render_wait"

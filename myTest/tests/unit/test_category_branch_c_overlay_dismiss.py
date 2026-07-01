"""分支 C 图片空间弹窗关闭。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_overlay_dismiss import (
    dismiss_branch_c_image_space_hint_tooltip,
    ensure_branch_c_blocking_overlays_cleared,
    wait_branch_c_category_page_advance,
)


def test_dismiss_image_space_hint_when_present():
    page = MagicMock()
    page.run_js.return_value = {"clicked": True, "method": "image_space_hint"}
    assert dismiss_branch_c_image_space_hint_tooltip(page) is True


def test_ensure_branch_c_blocking_overlays_calls_image_space():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_overlay_dismiss.dismiss_branch_c_image_space_hint_tooltip",
        return_value=False,
    ) as hint_mock, patch(
        "pdd_agent.skills.listing.listing_pdd_overlay_dismiss.ensure_image_space_modal_cleared",
        return_value=True,
    ) as image_mock:
        assert (
            ensure_branch_c_blocking_overlays_cleared(page, "store", "label") is True
        )
    hint_mock.assert_called_once_with(page)
    image_mock.assert_called_once()


def test_wait_branch_c_advance_clears_overlay_each_second(monkeypatch):
    page = MagicMock()
    states = iter([True, True, False])
    sleeps: list[float] = []

    monkeypatch.setattr(
        "pdd_agent.skills.listing.upload._is_still_on_category_publish_step",
        lambda _page: next(states, False),
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_overlay_dismiss.time",
        MagicMock(sleep=lambda s: sleeps.append(s)),
    )
    cleared = {"n": 0}

    def _clear(*_a, **_k):
        cleared["n"] += 1
        return True

    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_overlay_dismiss.ensure_branch_c_blocking_overlays_cleared",
        _clear,
    )

    assert wait_branch_c_category_page_advance(
        page, "store", "label", max_wait=5, mode="render_wait", ui_type="C"
    ) is True
    assert len(sleeps) == 2
    assert cleared["n"] == 2


def test_wait_branch_c_advance_retries_next_on_interval(monkeypatch):
    page = MagicMock()
    still_on = {"n": 12}

    def _still(_page):
        still_on["n"] -= 1
        return still_on["n"] > 0

    monkeypatch.setattr(
        "pdd_agent.skills.listing.upload._is_still_on_category_publish_step",
        _still,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_overlay_dismiss.time",
        MagicMock(sleep=lambda _s: None),
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_overlay_dismiss.ensure_branch_c_blocking_overlays_cleared",
        lambda *_a, **_k: True,
    )
    next_clicks = {"n": 0}
    monkeypatch.setattr(
        "pdd_agent.skills.listing.upload._click_branch_c_category_next",
        lambda *_a, **_k: next_clicks.__setitem__("n", next_clicks["n"] + 1)
        or (True, "e2e"),
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.upload._click_branch_c_category_recommendation",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_overlay_dismiss.clear_branch_c_overlays_before_category_next",
        lambda *_a, **_k: None,
    )

    assert wait_branch_c_category_page_advance(
        page, "store", "label", max_wait=10, mode="render_wait", ui_type="C"
    ) is True
    assert next_clicks["n"] == 1

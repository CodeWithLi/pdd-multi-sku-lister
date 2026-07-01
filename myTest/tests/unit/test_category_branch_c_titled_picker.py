"""分支 C 带标题「选择分类 → 最近使用 → 确认」测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_titled_picker import (
    branch_c_needs_titled_manual_category_pick,
    read_branch_c_titled_manual_state,
    run_branch_c_titled_manual_category_pick,
)


def _titled_entry_state() -> dict:
    return {
        "modalOpen": False,
        "selectButtonVisible": True,
        "searchOnMain": False,
        "blocking": True,
        "noRecommendation": True,
        "hasPublishForm": True,
        "recentPaths": [],
    }


def _titled_modal_state() -> dict:
    return {
        "modalOpen": True,
        "selectButtonVisible": False,
        "searchOnMain": False,
        "blocking": True,
        "noRecommendation": True,
        "hasPublishForm": True,
        "recentPaths": ["文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋"],
    }


def test_needs_titled_pick_when_select_button_and_title():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai", "title": "3D立体KT猫可爱笔袋"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.read_branch_c_titled_manual_state",
        return_value=_titled_entry_state(),
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_has_filled_title",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_image_category_recommendation_modal_visible",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_modal_blocking_category_advance",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        return_value=False,
    ):
        assert branch_c_needs_titled_manual_category_pick(page, listing_info) is True


def test_needs_titled_pick_false_without_title():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_has_filled_title",
        return_value=False,
    ):
        assert branch_c_needs_titled_manual_category_pick(page, {"title_mode": "page_ai"}) is False


def test_needs_titled_pick_false_when_search_on_main():
    page = MagicMock()
    state = _titled_entry_state()
    state["searchOnMain"] = True
    with patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.read_branch_c_titled_manual_state",
        return_value=state,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_has_filled_title",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_image_category_recommendation_modal_visible",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_modal_blocking_category_advance",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        return_value=False,
    ):
        assert branch_c_needs_titled_manual_category_pick(page, {"title_mode": "page_ai"}) is False


def test_run_titled_pick_opens_modal_and_confirms():
    page = MagicMock()
    states = iter([_titled_entry_state(), _titled_modal_state(), _titled_modal_state()])
    with patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.read_branch_c_titled_manual_state",
        lambda _page: next(states, _titled_modal_state()),
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        side_effect=[False, False, True],
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_click_select_category_button",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_click_first_recent_in_picker_modal",
        return_value=(True, "文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋"),
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_confirm_manual_category_picker_modal",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
    ), patch(
        "pdd_agent.skills.listing.upload._confirm_category_picker_selection",
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.time.sleep",
    ):
        ok = run_branch_c_titled_manual_category_pick(
            page,
            "store",
            "BD014A",
            {"title_mode": "page_ai"},
            max_wait=3,
        )
    assert ok is True


def test_read_state_returns_dict_on_error():
    page = MagicMock()
    page.run_js.side_effect = RuntimeError("boom")
    assert read_branch_c_titled_manual_state(page) == {}

"""分支 C 列选器/关键词选类。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_picker import (
    branch_c_needs_keyword_category_pick,
    prepare_branch_c_category_before_next,
    run_branch_c_keyword_category_pick,
)


def test_needs_keyword_pick_when_search_visible_but_path_not_ready():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_picker.branch_c_has_category_search_input",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_picker.branch_c_category_path_ready",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_modal_blocking_category_advance",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.upload._branch_c_category_already_selected",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_picker.branch_c_read_submit_state",
        return_value={"visible": True, "selectedPathReady": False, "blocking": False},
    ):
        assert branch_c_needs_keyword_category_pick(page) is True


def test_skip_keyword_pick_when_path_ready():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_picker.branch_c_category_path_ready",
        return_value=True,
    ):
        assert branch_c_needs_keyword_category_pick(page) is False


def test_prepare_branch_c_does_not_skip_when_button_visible_without_path():
    page = MagicMock()
    calls = {"wait": 0}

    def _wait(*_a, **_k):
        calls["wait"] += 1
        return True

    with patch(
        "pdd_agent.skills.listing.category_branch_c_picker.branch_c_read_submit_state",
        return_value={"visible": True, "disabled": False, "selectedPathReady": False},
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_picker.branch_c_category_path_ready",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_page_flow.wait_category_section_ready",
        side_effect=_wait,
    ), patch(
        "pdd_agent.skills.listing.upload._click_category_section_blank",
    ), patch(
        "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
    ):
        prepare_branch_c_category_before_next(
            page,
            "store_A",
            "AXBD001A/第二套图",
            category_mode="render_wait",
            burst_demo=False,
        )
    assert calls["wait"] == 1


def test_run_keyword_category_pick_three_steps():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.upload._select_category_by_keyword_search",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.upload._confirm_category_picker_selection",
    ), patch(
        "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_picker.branch_c_category_path_ready",
        side_effect=[False, True],
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_picker.time.sleep",
    ):
        ok = run_branch_c_keyword_category_pick(
            page,
            "store_A",
            "AXBD001A/第二套图",
            "笔袋",
            max_wait=3,
        )
    assert ok is True

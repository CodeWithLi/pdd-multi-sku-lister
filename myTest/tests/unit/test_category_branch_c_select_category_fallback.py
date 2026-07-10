"""分支 C「选择分类 → 最近使用 → 确认」兜底测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_orchestrator import (
    _run_strategy_simplified_manual,
)
from pdd_agent.skills.listing.category_branch_c_select_category_fallback import (
    is_branch_c_select_category_fallback_eligible,
    try_branch_c_select_category_recent_fallback,
)


def _fallback_state() -> dict:
    return {
        "modalOpen": False,
        "selectButtonVisible": True,
        "noRecommendation": True,
        "hasCategorySection": True,
        "recentPaths": [],
    }


def _fallback_modal_state() -> dict:
    return {
        "modalOpen": True,
        "selectButtonVisible": False,
        "noRecommendation": True,
        "hasCategorySection": True,
        "recentPaths": ["文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋"],
    }


def test_fallback_not_eligible_for_non_page_ai():
    page = MagicMock()
    assert (
        is_branch_c_select_category_fallback_eligible(
            page, {"title_mode": "custom"}
        )
        is False
    )


def test_fallback_eligible_with_select_button_and_title():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.is_branch_c_page_ai_title_listing",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_has_filled_title",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback._branch_c_fallback_category_ready",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_image_category_recommendation_modal_visible",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_modal_blocking_category_advance",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        return_value={"onPage": False},
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback.read_branch_c_select_category_fallback_state",
        return_value=_fallback_state(),
    ):
        assert (
            is_branch_c_select_category_fallback_eligible(
                page, {"title_mode": "page_ai"}
            )
            is True
        )


def test_fallback_skipped_when_not_eligible():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback.is_branch_c_select_category_fallback_eligible",
        return_value=False,
    ):
        assert (
            try_branch_c_select_category_recent_fallback(
                page, "store", "label", {"title_mode": "page_ai"}
            )
            is False
        )


def test_fallback_opens_modal_clicks_recent_and_confirms():
    page = MagicMock()
    states = iter([_fallback_state(), _fallback_modal_state(), _fallback_modal_state()])
    with patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback.is_branch_c_select_category_fallback_eligible",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback._branch_c_fallback_category_ready",
        side_effect=[False, False, True],
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback.read_branch_c_select_category_fallback_state",
        lambda _page: next(states, _fallback_modal_state()),
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback._click_select_category_button",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback._click_first_recent_in_modal",
        return_value=(True, "文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋"),
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback._confirm_picker_modal",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback._nudge_category_section",
    ), patch(
        "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
    ), patch(
        "pdd_agent.skills.listing.upload._confirm_category_picker_selection",
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback.time.sleep",
    ):
        ok = try_branch_c_select_category_recent_fallback(
            page,
            "store",
            "BD014A",
            {"title_mode": "page_ai"},
            max_wait=3,
        )
    assert ok is True


def test_fallback_swallows_exception():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_select_category_fallback.is_branch_c_select_category_fallback_eligible",
        side_effect=RuntimeError("boom"),
    ):
        assert (
            try_branch_c_select_category_recent_fallback(
                page, "store", "label", {"title_mode": "page_ai"}
            )
            is False
        )


def test_orchestrator_manual_falls_back_after_keyword_search_fails():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai", "title": "测试标题"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        side_effect=[False, True],
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_needs_titled_manual_category_pick",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_page_flow.prepare_category_before_next",
    ), patch(
        "pdd_agent.skills.listing.upload._open_category_selector_panel",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.upload._select_category_by_keyword_search",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator._try_select_category_recent_fallback",
        return_value=True,
    ) as fallback:
        ok = _run_strategy_simplified_manual(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    fallback.assert_called_once()


def test_orchestrator_manual_unchanged_when_keyword_search_succeeds():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai", "title": "测试标题"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        side_effect=[False, True],
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_needs_titled_manual_category_pick",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_page_flow.prepare_category_before_next",
    ), patch(
        "pdd_agent.skills.listing.upload._open_category_selector_panel",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.upload._select_category_by_keyword_search",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator._try_select_category_recent_fallback",
    ) as fallback:
        ok = _run_strategy_simplified_manual(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    fallback.assert_not_called()

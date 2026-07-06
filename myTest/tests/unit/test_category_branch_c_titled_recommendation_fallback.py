"""分支 C 带标题推荐卡片迟渲染兜底测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_orchestrator import (
    _run_strategy_simplified_manual,
)
from pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback import (
    branch_c_titled_simplified_category_ready,
    is_branch_c_titled_recommendation_fallback_eligible,
    try_recover_branch_c_titled_category_after_render_nudge,
)


def test_fallback_not_eligible_for_non_page_ai():
    page = MagicMock()
    assert (
        is_branch_c_titled_recommendation_fallback_eligible(
            page, {"title_mode": "custom"}
        )
        is False
    )


def test_fallback_not_eligible_on_traditional_on_page():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.is_branch_c_page_ai_title_listing",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_has_filled_title",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        return_value={"onPage": True},
    ):
        assert (
            is_branch_c_titled_recommendation_fallback_eligible(
                page, {"title_mode": "page_ai"}
            )
            is False
        )


def test_fallback_skipped_when_not_eligible():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback.is_branch_c_titled_recommendation_fallback_eligible",
        return_value=False,
    ):
        assert (
            try_recover_branch_c_titled_category_after_render_nudge(
                page, "store", "label", {"title_mode": "page_ai"}
            )
            is False
        )


def test_fallback_succeeds_when_category_already_ready():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback.is_branch_c_titled_recommendation_fallback_eligible",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback.branch_c_titled_simplified_category_ready",
        return_value=True,
    ):
        assert (
            try_recover_branch_c_titled_category_after_render_nudge(
                page, "store", "label", {"title_mode": "page_ai"}, max_wait=1
            )
            is True
        )


def test_fallback_clicks_recommendation_when_cards_visible():
    page = MagicMock()
    ready = iter([False, True])
    with patch(
        "pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback.is_branch_c_titled_recommendation_fallback_eligible",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback.branch_c_titled_simplified_category_ready",
        side_effect=lambda _p: next(ready),
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback._has_titled_recommendation_cards",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.upload._click_branch_c_category_recommendation",
    ) as click_rec:
        assert (
            try_recover_branch_c_titled_category_after_render_nudge(
                page, "store", "label", {"title_mode": "page_ai"}, max_wait=1
            )
            is True
        )
    click_rec.assert_called_once()


def test_titled_simplified_ready_uses_submit_state():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_modal_blocking_category_advance",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.upload._read_category_submit_state",
        return_value={"blocking": False, "selectedPathReady": True},
    ):
        assert branch_c_titled_simplified_category_ready(page) is True


def test_orchestrator_manual_falls_back_after_open_selector_fails():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai", "title": "测试标题"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_needs_titled_manual_category_pick",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_page_flow.prepare_category_before_next",
    ), patch(
        "pdd_agent.skills.listing.upload._open_category_selector_panel",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback.try_recover_branch_c_titled_category_after_render_nudge",
        return_value=True,
    ) as fallback:
        ok = _run_strategy_simplified_manual(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    fallback.assert_called_once()


def test_orchestrator_manual_unchanged_when_open_selector_succeeds():
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
        "pdd_agent.skills.listing.category_branch_c_titled_recommendation_fallback.try_recover_branch_c_titled_category_after_render_nudge",
    ) as fallback:
        ok = _run_strategy_simplified_manual(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    fallback.assert_not_called()

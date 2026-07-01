"""分支 C AI 标题页 — 下一步未跳转时的页面随机点击补救。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge import (
    advance_branch_c_category_after_ai_title_selection,
    branch_c_ai_title_nudge_enabled,
    nudge_then_retry_branch_c_category_next,
    random_human_nudge_clicks_on_publish_page,
)


def test_nudge_enabled_requires_ai_title_in_input():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title.branch_c_category_page_ai_title_applied",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
            return_value="爱心浮雕文具袋优雅收纳",
        ):
            assert branch_c_ai_title_nudge_enabled({"_branch_c_category_ai_title_applied": True}, page)


def test_nudge_then_retry_calls_random_clicks_before_next():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.upload._is_still_on_category_publish_step",
        side_effect=[True, True, False],
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.targeted_form_nudge_clicks_on_publish_page",
            return_value=3,
        ) as nudge:
            with patch(
                "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.click_branch_c_category_next_with_recommendation",
                return_value=True,
            ) as nxt:
                ok = nudge_then_retry_branch_c_category_next(
                    page, "store", "label", nudge_count=3
                )
    assert ok is True
    nudge.assert_called_once()
    nxt.assert_called_once_with(page, "store", "label", context="激活后")


def test_advance_nudges_when_first_next_stays_on_page():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai", "_branch_c_category_ai_title_applied": True}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.branch_c_ai_title_nudge_enabled",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.upload._wait_category_submit_ready",
        ):
            with patch(
                "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
            ):
                with patch(
                    "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.click_branch_c_category_next_with_recommendation",
                    return_value=True,
                ):
                    with patch(
                        "pdd_agent.skills.listing.upload._is_still_on_category_publish_step",
                        side_effect=[True, True, True, True, False],
                    ):
                        with patch(
                            "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.nudge_then_retry_branch_c_category_next",
                            return_value=True,
                        ) as nudge_retry:
                            with patch(
                                "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.wait_branch_c_category_advance_with_ai_nudge",
                                return_value=True,
                            ):
                                ok, err = advance_branch_c_category_after_ai_title_selection(
                                    page, "store", "label", listing_info
                                )
    assert ok is True
    assert err == ""
    assert nudge_retry.call_count == 2


def test_targeted_nudge_uses_playwright_mouse():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.upload._is_still_on_category_publish_step",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge._pick_targeted_nudge_point",
            return_value={"x": 400.0, "y": 300.0, "kind": "title"},
        ):
            with patch(
                "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge._mouse_at_point",
                return_value=True,
            ) as mouse:
                with patch(
                    "pdd_agent.skills.listing.upload._blur_page_focus",
                ):
                    count = random_human_nudge_clicks_on_publish_page(
                        page, "store", "label", count=3
                    )
    assert count == 3
    assert mouse.call_count == 3

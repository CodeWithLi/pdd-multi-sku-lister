"""下一步点击成功日志测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge import (
    click_branch_c_category_next_with_recommendation,
)


def test_logs_success_when_next_clicked_but_still_on_page(capsys):
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge._ensure_branch_c_category_for_ai_next",
        ):
            with patch(
                "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.click_branch_c_next_two_step_trusted",
                return_value=(True, "mouse/e2e-publish-button"),
            ):
                with patch(
                    "pdd_agent.skills.listing.upload._is_still_on_category_publish_step",
                    return_value=True,
                ):
                    ok = click_branch_c_category_next_with_recommendation(
                        page, "store", "label", context="激活后"
                    )
    assert ok is True
    out = capsys.readouterr().out
    assert "已成功点击「下一步」" in out
    assert "激活后" in out
    assert "页面尚未跳转" in out


def test_logs_success_when_next_clicked_and_advanced(capsys):
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge._ensure_branch_c_category_for_ai_next",
        ):
            with patch(
                "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.click_branch_c_next_two_step_trusted",
                return_value=(True, "mouse/beast-core-button"),
            ):
                with patch(
                    "pdd_agent.skills.listing.upload._is_still_on_category_publish_step",
                    return_value=False,
                ):
                    ok = click_branch_c_category_next_with_recommendation(
                        page, "store", "label", context="首次"
                    )
    assert ok is True
    out = capsys.readouterr().out
    assert "已成功点击「下一步」" in out
    assert "页面已跳转" in out

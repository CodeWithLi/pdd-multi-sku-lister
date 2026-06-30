"""分支 C 下一步按钮点击。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_next import (
    BRANCH_C_NEXT_SELECTORS,
    click_branch_c_category_next_button,
)


def test_branch_c_next_selectors_include_e2e_publish():
    assert 'css:button[data-e2e-id="e2e-publish-button"]' in BRANCH_C_NEXT_SELECTORS


def test_click_branch_c_prefers_e2e_selector():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_next._click_via_playwright_locator",
        side_effect=[True, False, False],
    ) as mock_click, patch(
        "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_next._scroll_to_next_button",
    ):
        ok, method = click_branch_c_category_next_button(page, "store_A", "AXBD001A/第一套图")
    assert ok is True
    assert mock_click.call_count == 1
    assert "e2e-publish-button" in method

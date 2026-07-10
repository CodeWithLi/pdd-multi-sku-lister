"""待报名商品区块守卫。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.campaign.marketing_activity_pending_section_guard import (
    dismiss_unexpected_pending_modals,
    prepare_marketing_registration_surface,
    scroll_to_marketing_registration_section,
)


def test_scroll_to_registration_section():
    page = MagicMock()
    page.run_js.return_value = {"scrolled": True, "method": "marketing_registration_title"}
    out = scroll_to_marketing_registration_section(page, "store1")
    assert out.get("scrolled") is True


def test_dismiss_unexpected_modal():
    page = MagicMock()
    page.run_js.return_value = {
        "dismissed": True,
        "present": True,
        "title": "搜索活动商品",
        "click": {"clicked": True, "method": "cancel_button"},
    }
    out = dismiss_unexpected_pending_modals(page, "store1")
    assert out.get("dismissed") is True


def test_prepare_surface_runs_all_steps():
    page = MagicMock()
    page.run_js.side_effect = [
        {"dismissed": False, "present": False},
        {"unchecked": 3, "acted": True},
        {"scrolled": True, "method": "marketing_registration_title"},
    ]
    out = prepare_marketing_registration_surface(page, "store1")
    assert out.get("ready") is True
    assert out["unchecked"].get("unchecked") == 3

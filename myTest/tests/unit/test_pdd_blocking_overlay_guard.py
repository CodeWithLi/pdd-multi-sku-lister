"""拼多多统一遮罩守卫。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.pdd_blocking_overlay_guard import (
    clear_one_pdd_blocking_overlay,
    ensure_pdd_blocking_overlays_cleared,
)


def test_clear_one_uses_registration_notice_handler_before_address_page():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.upload._dismiss_business_address_registration_notice",
        return_value=True,
    ) as notice, patch(
        "pdd_agent.skills.listing.upload._dismiss_address_required_page",
        return_value=False,
    ) as addr:
        out = clear_one_pdd_blocking_overlay(page, "store", "label")
    notice.assert_called_once()
    addr.assert_not_called()
    assert out == {"acted": True, "source": "address_required"}


def test_clear_one_uses_existing_address_handler_first():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.upload._dismiss_business_address_registration_notice",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.upload._dismiss_address_required_page",
        return_value=True,
    ) as addr:
        out = clear_one_pdd_blocking_overlay(page, "store", "label")
    addr.assert_called_once()
    assert out == {"acted": True, "source": "address_required"}


def test_clear_one_generic_when_handlers_miss():
    page = MagicMock()
    page.run_js.side_effect = [
        False,
        {
            "acted": True,
            "clicked": True,
            "source": "generic_safe_modal",
            "method": "close_icon",
            "preview": "待处理",
        },
    ]
    with patch(
        "pdd_agent.skills.listing.upload._dismiss_business_address_registration_notice",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.upload._dismiss_address_required_page",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.listing_pdd_overlay_dismiss.dismiss_post_publish_goods_list_modal",
        return_value=False,
    ):
        out = clear_one_pdd_blocking_overlay(page, "store", "label")
    assert out.get("acted") is True
    assert out.get("source") == "generic_safe_modal"


def test_clear_one_skips_business_protected():
    page = MagicMock()
    page.run_js.side_effect = [
        False,
        {"acted": False, "skipped": True, "reason": "business_protected"},
    ]
    with patch(
        "pdd_agent.skills.listing.upload._dismiss_business_address_registration_notice",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.upload._dismiss_address_required_page",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.listing_pdd_overlay_dismiss.dismiss_post_publish_goods_list_modal",
        return_value=False,
    ):
        out = clear_one_pdd_blocking_overlay(page, "store", "label")
    assert out.get("skipped") is True


def test_ensure_loops_until_no_action():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.pdd_blocking_overlay_guard.clear_one_pdd_blocking_overlay",
        side_effect=[
            {"acted": True, "source": "post_publish_pending"},
            {"acted": True, "source": "address_required"},
            {"acted": False},
        ],
    ) as clear_one:
        assert ensure_pdd_blocking_overlays_cleared(page, "store", "label", max_attempts=5) is True
    assert clear_one.call_count == 3

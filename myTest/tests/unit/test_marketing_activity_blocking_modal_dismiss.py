"""营销活动页遮挡弹窗关闭。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.campaign.marketing_activity_blocking_modal_dismiss import (
    detect_marketing_blocking_modal,
    dismiss_one_marketing_blocking_modal,
    ensure_marketing_blocking_modals_cleared,
)


def test_detect_no_modal():
    page = MagicMock()
    page.run_js.return_value = {"present": False, "acted": False, "reason": "no_modal"}
    out = detect_marketing_blocking_modal(page)
    assert out.get("present") is False


def test_detect_eligibility_warning_modal():
    page = MagicMock()
    page.run_js.return_value = {
        "present": True,
        "dismissible": True,
        "preview": "您有14个商品因不符合活动要求即将影响活动权益请尽快修改",
        "has_close_icon": True,
        "has_later_button": True,
        "safe_marker": True,
    }
    out = detect_marketing_blocking_modal(page)
    assert out.get("dismissible") is True
    assert out.get("has_close_icon") is True


def test_dismiss_clicks_close_icon():
    page = MagicMock()
    page.run_js.return_value = {
        "present": True,
        "acted": True,
        "clicked": True,
        "method": "modal_close_icon",
        "preview": "不符合活动要求",
        "safe_marker": True,
    }
    out = dismiss_one_marketing_blocking_modal(page, "store1")
    assert out.get("acted") is True
    assert out.get("method") == "modal_close_icon"


def test_dismiss_skips_business_protected():
    page = MagicMock()
    page.run_js.return_value = {
        "present": True,
        "acted": False,
        "skipped": True,
        "reason": "business_protected",
        "preview": "搜索商品",
    }
    out = dismiss_one_marketing_blocking_modal(page, "store1")
    assert out.get("skipped") is True


def test_ensure_loops_until_no_action():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.campaign.marketing_activity_blocking_modal_dismiss.dismiss_one_marketing_blocking_modal",
        side_effect=[
            {"acted": True, "method": "modal_close_icon"},
            {"acted": True, "method": "later_button"},
            {"acted": False, "reason": "no_modal"},
        ],
    ) as dismiss_one:
        out = ensure_marketing_blocking_modals_cleared(page, "store1", max_attempts=5)
    assert dismiss_one.call_count == 3
    assert out["cleared"] == 2
    assert out["dismissed"] is True

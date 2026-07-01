"""拼多多遮罩弹窗关闭。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
    dismiss_image_space_modal,
    dismiss_post_publish_goods_list_modal,
    ensure_image_space_modal_cleared,
)


def test_dismiss_image_space_when_present():
    page = MagicMock()
    page.run_js.side_effect = [True, {"present": True, "clicked": True, "method": "close_icon"}]
    assert dismiss_image_space_modal(page, "store", "label") is True


def test_skip_image_space_when_absent():
    page = MagicMock()
    page.run_js.return_value = False
    assert dismiss_image_space_modal(page, "store", "label") is False


def test_ensure_image_space_cleared():
    page = MagicMock()
    page.run_js.side_effect = [
        True,
        True,
        {"present": True, "clicked": True, "method": "close_icon"},
        False,
    ]
    assert ensure_image_space_modal_cleared(page, "store", "label", max_attempts=2) is True


def test_dismiss_post_publish_modal():
    page = MagicMock()
    page.run_js.side_effect = [True, {"present": True, "clicked": True, "method": "top_right_candidate"}]
    assert dismiss_post_publish_goods_list_modal(page, "store", "label") is True

"""分支 C 推荐分类弹窗检测。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_modal import (
    _looks_like_category_option,
    body_text_indicates_recommendation_modal,
    handle_image_category_recommendation_modal,
    is_image_category_recommendation_modal_visible,
)


def test_body_text_indicates_recommendation_modal():
    body = "根据您上传的图片，为您推荐分类，请选择： 确认 取消"
    assert body_text_indicates_recommendation_modal(body) is True


def test_body_text_modal_not_visible_without_confirm():
    body = "商品分类 笔袋/文具袋"
    assert body_text_indicates_recommendation_modal(body) is False


def test_looks_like_category_option_rejects_modal_title():
    text = "根据您上传的图片，为您推荐分类，请选择： 笔袋/文具袋 文具盒/笔盒"
    assert _looks_like_category_option(text) is False


def test_looks_like_category_option_accepts_path():
    text = "文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋"
    assert _looks_like_category_option(text) is True


def test_modal_visible_from_body_text_fallback():
    page = MagicMock()
    page.run_js.side_effect = [
        {"visible": False, "hasRoot": False, "bodyMatch": False},
        "根据您上传的图片，为您推荐分类，请选择 确认 取消",
    ]
    assert is_image_category_recommendation_modal_visible(page) is True


def test_modal_visible_from_js():
    page = MagicMock()
    page.run_js.return_value = {"visible": True, "hasRoot": True, "bodyMatch": False}
    assert is_image_category_recommendation_modal_visible(page) is True


def test_handle_modal_only_succeeds_when_closed():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_image_category_recommendation_modal_visible",
        side_effect=[True, True, False],
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_modal._attempt_close_recommendation_modal",
        return_value=(True, "笔袋/文具袋"),
    ):
        assert handle_image_category_recommendation_modal(page, "store_A", "BD050B") is True


def test_handle_modal_fails_if_still_open_after_click():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_image_category_recommendation_modal_visible",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_modal._attempt_close_recommendation_modal",
        return_value=(False, ""),
    ):
        assert handle_image_category_recommendation_modal(page, "store_A", "BD050B") is False

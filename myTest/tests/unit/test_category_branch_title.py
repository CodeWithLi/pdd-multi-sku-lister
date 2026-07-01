"""分支 C 标题策略：分类页跳过 AI 等待，详情页再填。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_title import (
    apply_title_after_branch_c_category_advance,
    apply_title_after_branch_c_cover_upload,
    apply_title_after_cover_upload_for_branch,
)


def test_branch_c_cover_upload_skips_page_ai_wait():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
        return_value="",
    ), patch(
        "pdd_agent.skills.listing.page_ai_title.is_page_ai_title_mode",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.page_ai_title.apply_title_after_cover_upload",
    ) as mock_apply:
        title = apply_title_after_branch_c_cover_upload(
            page,
            "store_A",
            {"title_mode": "page_ai"},
            "预生成标题",
            label="AXBD001A",
        )
    assert title == "预生成标题"
    mock_apply.assert_not_called()


def test_branch_c_cover_upload_returns_existing_title():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
        return_value="已有标题",
    ):
        title = apply_title_after_branch_c_cover_upload(
            page,
            "store_A",
            {},
            "",
            label="AXBD001A",
        )
    assert title == "已有标题"


def test_branch_ab_still_uses_page_ai_on_category_page():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.page_ai_title.apply_title_after_cover_upload",
        return_value="AI标题",
    ) as mock_apply:
        title = apply_title_after_cover_upload_for_branch(
            page,
            "store_A",
            {},
            "",
            ui_type="A",
            phase="category_page",
        )
    assert title == "AI标题"
    mock_apply.assert_called_once()


def test_branch_c_details_page_applies_page_ai():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
        return_value="",
    ), patch(
        "pdd_agent.skills.listing.page_ai_title.is_page_ai_title_mode",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.page_ai_title.try_apply_branch_c_ai_title_generate_dropdown",
        return_value="蕾丝心形笔袋优雅收纳",
    ) as mock_dropdown, patch(
        "pdd_agent.skills.listing.page_ai_title.apply_title_after_cover_upload",
    ) as mock_apply:
        title = apply_title_after_branch_c_category_advance(
            page,
            "store_A",
            {"title_mode": "page_ai"},
            "",
            label="AXBD001A",
        )
    assert title == "蕾丝心形笔袋优雅收纳"
    mock_dropdown.assert_called_once()
    mock_apply.assert_not_called()

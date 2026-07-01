"""分支 C page_ai 标题轮询重试测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_page_ai_title_retry import (
    detect_branch_c_ai_title_recommendation_bar,
    ensure_branch_c_page_ai_title_before_category,
    is_branch_c_page_ai_title_listing,
    retry_apply_branch_c_page_ai_title,
)


def test_is_branch_c_page_ai_title_listing():
    with patch(
        "pdd_agent.skills.listing.page_ai_title.is_page_ai_title_mode",
        return_value=True,
    ):
        assert is_branch_c_page_ai_title_listing({"title_mode": "page_ai"}) is True


def test_detect_ai_bar_slash_variant():
    page = MagicMock()
    page.run_js.return_value = {
        "visible": True,
        "variant": "AI/智能推荐标题",
        "hasUseNow": True,
    }
    bar = detect_branch_c_ai_title_recommendation_bar(page)
    assert bar["visible"] is True
    assert bar["variant"] == "AI/智能推荐标题"


def test_retry_returns_existing_title_without_poll():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.page_ai_title.is_page_ai_title_mode",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
            return_value="奶油色蕾丝文具收纳袋",
        ):
            title, applied = retry_apply_branch_c_page_ai_title(
                page, "store", {"title_mode": "page_ai"}, label="x"
            )
    assert applied is True
    assert title == "奶油色蕾丝文具收纳袋"


def test_retry_clicks_use_now_when_bar_appears():
    page = MagicMock()
    reads = ["", "奶油色蕾丝文具收纳袋"]

    def read_title(_page):
        return reads.pop(0) if reads else "奶油色蕾丝文具收纳袋"

    with patch(
        "pdd_agent.skills.listing.page_ai_title.is_page_ai_title_mode",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
            side_effect=read_title,
        ):
            with patch(
                "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.detect_branch_c_ai_title_recommendation_bar",
                return_value={"visible": True, "variant": "AI/智能推荐标题", "hasUseNow": True},
            ):
                with patch(
                    "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry._try_apply_use_now_once",
                    return_value=True,
                ):
                    with patch("time.sleep"):
                        title, applied = retry_apply_branch_c_page_ai_title(
                            page,
                            "store",
                            {"title_mode": "page_ai"},
                            initial_wait=0,
                            max_wait=3,
                            label="x",
                        )
    assert applied is True
    assert "奶油色" in title


def test_ensure_before_category_retries_when_bar_visible():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai", "title": ""}
    with patch(
        "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
        return_value="",
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.detect_branch_c_ai_title_recommendation_bar",
            return_value={"visible": True, "hasUseNow": True},
        ):
            with patch(
                "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.retry_apply_branch_c_page_ai_title",
                return_value=("奶油色蕾丝文具收纳袋", True),
            ) as retry:
                title, applied = ensure_branch_c_page_ai_title_before_category(
                    page,
                    "store",
                    listing_info,
                    listing_info,
                    label="AXBD001A",
                )
    assert applied is True
    assert title == "奶油色蕾丝文具收纳袋"
    assert listing_info["_branch_c_category_ai_title_applied"] is True
    retry.assert_called_once()


def test_ensure_before_category_skips_when_no_bar():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai"}
    with patch(
        "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
        return_value="",
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.detect_branch_c_ai_title_recommendation_bar",
            return_value={"visible": False, "hasUseNow": False},
        ):
            with patch(
                "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.retry_apply_branch_c_page_ai_title",
            ) as retry:
                title, applied = ensure_branch_c_page_ai_title_before_category(
                    page, "store", listing_info, listing_info, label="x"
                )
    assert applied is False
    retry.assert_not_called()

"""分支 C 分类页 AI 推荐标题（立即使用）兼容测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
    META_KEY_CATEGORY_AI_APPLIED,
    apply_branch_c_category_page_ai_title_when_visible,
    branch_c_category_page_ai_title_visible,
    branch_c_is_simplified_ai_title_publish_page,
    click_branch_c_category_next_with_ai_burst,
    ensure_branch_c_category_ready_for_ai_title_flow,
    prepare_branch_c_cover_upload_title,
)


def test_branch_c_category_page_ai_title_visible_detects_bar():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.branch_c_category_page_ai_title_bar_visible",
        return_value=True,
    ):
        assert branch_c_category_page_ai_title_visible(page) is True


def test_apply_skips_when_not_page_ai_mode():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title.branch_c_category_page_ai_title_visible",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.page_ai_title.is_page_ai_title_mode",
            return_value=False,
        ):
            title, applied = apply_branch_c_category_page_ai_title_when_visible(
                page, "store", {}, label="BD001A"
            )
    assert title == ""
    assert applied is False


def test_prepare_page_ai_uses_retry_not_legacy_skip():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title._listing_uses_page_ai_title_mode",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.retry_apply_branch_c_page_ai_title",
            return_value=("", False),
        ) as retry:
            with patch(
                "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
                return_value="",
            ):
                with patch(
                    "pdd_agent.skills.listing.category_branch_title.apply_title_after_branch_c_cover_upload",
                ) as legacy:
                    title, applied = prepare_branch_c_cover_upload_title(
                        page, "store", {"title_mode": "page_ai"}, "预生成标题", label="x"
                    )
    retry.assert_called_once()
    legacy.assert_not_called()
    assert applied is False
    assert title == "预生成标题"


def test_prepare_uses_legacy_path_when_not_page_ai():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title._listing_uses_page_ai_title_mode",
        return_value=False,
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_page_ai_title.apply_branch_c_category_page_ai_title_when_visible",
            return_value=("", False),
        ):
            with patch(
                "pdd_agent.skills.listing.category_branch_title.apply_title_after_branch_c_cover_upload",
                return_value="预生成标题",
            ) as legacy:
                title, applied = prepare_branch_c_cover_upload_title(
                    page, "store", {"title_mode": "manual"}, "预生成标题", label="x"
                )
    assert title == "预生成标题"
    assert applied is False
    legacy.assert_called_once()


def test_prepare_marks_applied_when_page_ai_title_in_input():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title._listing_uses_page_ai_title_mode",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.retry_apply_branch_c_page_ai_title",
            return_value=("", False),
        ):
            with patch(
                "pdd_agent.skills.listing.page_ai_title._read_title_from_input",
                return_value="素心雅境文具装饰桌布",
            ):
                title, applied = prepare_branch_c_cover_upload_title(
                    page, "store", {"title_mode": "page_ai"}, "", label="x"
                )
    assert applied is True
    assert title == "素心雅境文具装饰桌布"


def test_simplified_ai_title_page_skips_category_selection():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title.branch_c_is_simplified_ai_title_publish_page",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_recent.ensure_branch_c_category_selected",
        ) as legacy:
            ok = ensure_branch_c_category_ready_for_ai_title_flow(
                page, "store", "label", listing_info, "笔袋"
            )
    assert ok is True
    assert listing_info[META_KEY_CATEGORY_AI_APPLIED] is True
    legacy.assert_not_called()


def test_simplified_detection_false_on_traditional_category_page():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        return_value={"onPage": True, "pathReady": False},
    ):
        assert branch_c_is_simplified_ai_title_publish_page(page, {"title_mode": "page_ai"}) is False


def test_prepare_uses_ai_bar_when_visible():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_page_ai_title._listing_uses_page_ai_title_mode",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_page_ai_title_retry.retry_apply_branch_c_page_ai_title",
            return_value=("AI推荐标题", True),
        ):
            title, applied = prepare_branch_c_cover_upload_title(
                page, "store", {"title_mode": "page_ai"}, "", label="x"
            )
    assert title == "AI推荐标题"
    assert applied is True


def test_click_next_uses_ai_title_nudge_when_enabled():
    page = MagicMock()
    listing_info = {META_KEY_CATEGORY_AI_APPLIED: True}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.branch_c_ai_title_nudge_enabled",
        return_value=True,
    ):
        with patch(
            "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.advance_branch_c_category_after_ai_title_selection",
            return_value=(True, ""),
        ) as advance:
            ok, err = click_branch_c_category_next_with_ai_burst(
                page,
                "store",
                "label",
                listing_info,
                category_mode="render_wait",
                category_next_burst_demo=False,
            )
    assert ok is True
    assert err == ""
    advance.assert_called_once()


def test_click_next_falls_back_to_legacy_burst_without_ai_title():
    page = MagicMock()
    listing_info = {}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_ai_title_next_nudge.branch_c_ai_title_nudge_enabled",
        return_value=False,
    ):
        with patch(
            "pdd_agent.skills.listing.category_page_flow.click_category_next_and_advance",
            return_value=(True, ""),
        ) as legacy:
            ok, err = click_branch_c_category_next_with_ai_burst(
                page,
                "store",
                "label",
                listing_info,
                category_mode="render_wait",
                category_next_burst_demo=True,
            )
    assert ok is True
    legacy.assert_called_once()
    assert legacy.call_args.kwargs["burst_demo"] is True

"""分类页下一步失败具体说明。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.integrations.feishu.pdd_upload_sync import _format_brief_listing_failure_reason
from pdd_agent.skills.listing.category_next_step_failure_detail import (
    build_category_next_step_failure_detail,
    collect_category_next_step_issues,
)


def test_collect_category_next_step_issues_blocking(monkeypatch):
    import pdd_agent.skills.listing.upload as listing_upload

    page = MagicMock()
    monkeypatch.setattr(listing_upload, "_category_page_body_text", lambda _p: "请选择完整的分类")
    monkeypatch.setattr(
        listing_upload,
        "_read_category_submit_state",
        lambda _p: {"visible": True, "disabled": True, "blocking": True},
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        lambda _p: {"onPage": True, "blocking": True, "pathReady": False},
    )
    monkeypatch.setattr(listing_upload, "_branch_c_carousel_upload_count", lambda _p: (5, 10))
    monkeypatch.setattr(listing_upload, "_branch_c_category_already_selected", lambda _p: False)
    monkeypatch.setattr(listing_upload, "_category_page_needs_manual_selection", lambda _p: False)
    monkeypatch.setattr(listing_upload, "_is_image_category_recommendation_modal_visible", lambda _p: False)
    monkeypatch.setattr(listing_upload, "_is_still_on_category_publish_step", lambda _p: True)
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_modal.is_modal_blocking_category_advance",
        lambda _p: False,
    )

    issues = collect_category_next_step_issues(page, ui_type="C")
    assert "商品类目未选完整（页面提示：请选择完整的分类）" in issues
    assert "「下一步」按钮仍为禁用状态（类目或页面校验未通过）" in issues


def test_collect_category_next_step_issues_modal_and_no_carousel(monkeypatch):
    import pdd_agent.skills.listing.upload as listing_upload

    page = MagicMock()
    monkeypatch.setattr(listing_upload, "_category_page_body_text", lambda _p: "商品分类")
    monkeypatch.setattr(
        listing_upload,
        "_read_category_submit_state",
        lambda _p: {"visible": False, "disabled": True, "blocking": False},
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        lambda _p: {"onPage": False, "blocking": False, "pathReady": False},
    )
    monkeypatch.setattr(listing_upload, "_branch_c_carousel_upload_count", lambda _p: (0, 10))
    monkeypatch.setattr(listing_upload, "_branch_c_category_already_selected", lambda _p: False)
    monkeypatch.setattr(listing_upload, "_category_page_needs_manual_selection", lambda _p: False)
    monkeypatch.setattr(listing_upload, "_is_image_category_recommendation_modal_visible", lambda _p: True)
    monkeypatch.setattr(listing_upload, "_is_still_on_category_publish_step", lambda _p: True)
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_modal.is_modal_blocking_category_advance",
        lambda _p: True,
    )

    issues = collect_category_next_step_issues(page, ui_type="C")
    assert "「根据图片推荐分类」弹窗未确认，挡住了下一步" in issues
    assert "主图/轮播图未上传（当前 0/10 张）" in issues
    assert "页面上未显示「下一步，完善商品信息」按钮" in issues


def test_build_category_next_step_failure_detail_with_merchant_code(monkeypatch):
    import pdd_agent.skills.listing.upload as listing_upload

    page = MagicMock()
    monkeypatch.setattr(listing_upload, "_category_page_body_text", lambda _p: "请选择完整的分类")
    monkeypatch.setattr(
        listing_upload,
        "_read_category_submit_state",
        lambda _p: {"visible": True, "disabled": True, "blocking": True},
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        lambda _p: {"onPage": True, "blocking": True, "pathReady": False},
    )
    monkeypatch.setattr(listing_upload, "_branch_c_carousel_upload_count", lambda _p: (5, 10))
    monkeypatch.setattr(listing_upload, "_branch_c_category_already_selected", lambda _p: False)
    monkeypatch.setattr(listing_upload, "_category_page_needs_manual_selection", lambda _p: False)
    monkeypatch.setattr(listing_upload, "_is_image_category_recommendation_modal_visible", lambda _p: False)
    monkeypatch.setattr(listing_upload, "_is_still_on_category_publish_step", lambda _p: True)
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_modal.is_modal_blocking_category_advance",
        lambda _p: False,
    )

    detail = build_category_next_step_failure_detail(page, merchant_code="BD022A", ui_type="C")
    assert detail.startswith("BD022A")
    assert "请选择完整的分类" in detail


def test_compact_feishu_line_category_next_step_no_advance_detail():
    detail = "BD022A商品类目未选完整（页面提示：请选择完整的分类）"
    line = ListingErrors.compact_feishu_line(
        detail,
        reason_code=ListingErrorCode.CATEGORY_NEXT_STEP_NO_ADVANCE,
        merchant_code="BD022A",
    )
    assert line == detail
    assert line != ListingErrors.FEISHU_LABELS[ListingErrorCode.CATEGORY_NEXT_STEP_NO_ADVANCE]


def test_format_brief_listing_failure_reason_category_next_step():
    text = _format_brief_listing_failure_reason(
        listing_label="BD022A音乐小猫笔袋/第一套图",
        reason_code=ListingErrorCode.CATEGORY_NEXT_STEP_NO_ADVANCE,
        message="BD022A已点击「下一步」，但页面仍停留在分类页，未能进入商品详情",
        merchant_code="BD022A",
    )
    assert "未能进入商品详情" in text

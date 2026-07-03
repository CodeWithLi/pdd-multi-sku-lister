"""publish_settings_incomplete 具体说明。"""

from __future__ import annotations

from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.integrations.feishu.pdd_upload_sync import _format_brief_listing_failure_reason
from pdd_agent.skills.listing.publish_settings_failure_detail import (
    build_publish_settings_failure_detail,
    collect_publish_settings_issues,
)


def test_collect_publish_settings_issues_bulk_and_shipping():
    issues = collect_publish_settings_issues(
        {
            "ok": False,
            "bulk_discount": {
                "ok": False,
                "reason": "guard_verify_failed",
                "guard": "fill_failed",
                "final_state": {"input_value": "9.5", "visible_value": "9.5"},
            },
            "service_section": {
                "ok": False,
                "reason": "shipping_form_not_ready",
                "state": {"expandButtonVisible": True, "formReady": False},
            },
            "shipping_template": {
                "ok": False,
                "reason": "template_not_selected",
                "state": {"current": "", "otherChecked": False},
                "visibleOptions": ["标准模板", "包邮模板"],
            },
        }
    )
    assert any("满件折扣补填3次后仍未达到目标值" in x for x in issues)
    assert any("输入框=9.5" in x for x in issues)
    assert any("服务与承诺" in x for x in issues)
    assert any("未能选中运费模板「最新全国」" in x for x in issues)
    assert any("可见选项=标准模板、包邮模板" in x for x in issues)


def test_build_publish_settings_failure_detail_with_merchant_code():
    detail = build_publish_settings_failure_detail(
        {
            "ok": False,
            "bulk_discount": {"ok": False, "reason": "discount_input_not_found"},
            "shipping_template": {"ok": True},
            "service_section": {"ok": True},
        },
        merchant_code="BD022A",
    )
    assert detail == "BD022A未找到「满2件折扣」输入框（目标应为 9.9 折）"


def test_compact_feishu_line_publish_settings_detail():
    detail = "BD022A未能选中运费模板「最新全国」（当前=包邮模板）"
    line = ListingErrors.compact_feishu_line(
        detail,
        reason_code=ListingErrorCode.PUBLISH_SETTINGS_INCOMPLETE,
        merchant_code="BD022A",
    )
    assert line == detail
    assert line != ListingErrors.FEISHU_LABELS[ListingErrorCode.PUBLISH_SETTINGS_INCOMPLETE]


def test_format_brief_listing_failure_reason_publish_settings():
    text = _format_brief_listing_failure_reason(
        listing_label="BD022A/第一套图",
        reason_code=ListingErrorCode.PUBLISH_SETTINGS_INCOMPLETE,
        message="BD022A满件折扣补填3次后仍未达到目标值（当前输入框=9.5，目标应为 9.9 折）",
        merchant_code="BD022A",
    )
    assert "9.5" in text
    assert "9.9" in text

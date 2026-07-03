"""规格校验填表失败说明单元测试。"""

from __future__ import annotations

from pdd_agent.domain.listing_errors import ListingErrorCode
from pdd_agent.integrations.feishu.pdd_upload_sync import _format_brief_listing_failure_reason
from pdd_agent.skills.listing.listing_spec_fill_failure_detail import (
    describe_spec_fill_issue,
    format_spec_fill_verify_feishu_reason,
)


def test_describe_slot_catalog_mismatch():
    line = describe_spec_fill_issue(
        {
            "combo_folder": "BD068Q+YKL632A",
            "catalog_size": "笔袋+挂件",
            "slot_size": "笔袋+套尺",
            "reason": "slot_catalog_mismatch",
        }
    )
    assert line == "BD068Q+YKL632A 商品表「笔袋+挂件」≠页面槽位「笔袋+套尺」"


def test_format_spec_fill_verify_feishu_reason_numbered():
    text = format_spec_fill_verify_feishu_reason(
        {
            "price_filled": 50,
            "price_total": 50,
            "verify_passed_count": 46,
            "verify_total": 50,
            "slot_catalog_mismatches": [
                {
                    "combo_folder": "BD068Q+YKL632A",
                    "catalog_size": "笔袋+挂件",
                    "slot_size": "笔袋+套尺",
                },
                {
                    "combo_folder": "BD068Q+YKL031M",
                    "catalog_size": "笔袋+套尺",
                    "slot_size": "笔袋+挂件",
                },
            ],
            "verify_issues": [],
        }
    )
    assert "1、" in text
    assert "BD068Q+YKL632A" in text
    assert "商品表" in text
    assert "页面槽位" in text
    assert "spec_fill" not in text.lower()


def test_format_brief_listing_failure_reason_spec_fill_verify():
    detail = format_spec_fill_verify_feishu_reason(
        {
            "price_filled": 48,
            "price_total": 50,
            "failed_items": [
                {
                    "style": "白色-Q",
                    "size": "笔袋+套尺",
                    "combo_folder": "BD068Q+YKL632A",
                    "reason": "fill_failed",
                }
            ],
        }
    )
    brief = _format_brief_listing_failure_reason(
        listing_label="BD068A/第一套图",
        reason_code=ListingErrorCode.SPEC_FILL_VERIFY_FAILED,
        error=detail,
        message=detail,
        merchant_code="BD068A",
    )
    assert brief.startswith("仅填48/50行")
    assert "BD068Q+YKL632A" in brief
    assert "格位填写失败" in brief
    assert "spec_fill_verify_failed" not in brief

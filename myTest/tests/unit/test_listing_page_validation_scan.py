"""validation_incomplete / validation_errors 具体缺项说明。"""

from __future__ import annotations

from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.integrations.feishu.pdd_upload_sync import _format_brief_listing_failure_reason
from pdd_agent.skills.listing.listing_page_validation_scan import (
    build_validation_detail,
    build_validation_incomplete_detail,
    collect_listing_validation_issues,
    collect_validation_incomplete_issues,
)


def test_collect_validation_incomplete_issues_price_gaps():
    issues = collect_validation_incomplete_issues(
        price_gaps=[
            {"style": "蓝色", "size": "笔袋", "missing": ["库存", "拼团价"]},
            {"style": "蓝色", "size": "笔袋+挂件", "missing": ["规格编码"]},
        ]
    )
    assert issues == [
        "规格「蓝色/笔袋」缺库存、拼团价",
        "规格「蓝色/笔袋+挂件」缺规格编码",
    ]


def test_collect_listing_validation_issues_preview_and_red_errors():
    issues = collect_listing_validation_issues(
        preview_gaps=[
            {"style": "黄色", "size": "笔袋+挂件", "spec_code": "BD199A+PS004A"},
        ],
        page_errors=[
            {"type": "field", "field": "品牌", "message": "请填写品牌"},
            {"type": "sku_row", "style": "黄色", "size": "笔袋", "message": "拼单价不能为空"},
            {"type": "hint", "message": "还有2个错误项未处理"},
        ],
        carousel_current=2,
        carousel_total=5,
    )
    assert "规格「黄色/笔袋+挂件」缺规格预览图（编码 BD199A+PS004A）" in issues
    assert "品牌：请填写品牌" in issues
    assert "规格「黄色/笔袋」拼单价不能为空" in issues
    assert "轮播图仅 2/5 张" in issues


def test_build_validation_incomplete_detail_with_merchant_code():
    detail = build_validation_incomplete_detail(
        merchant_code="BD022A",
        price_gaps=[{"style": "蓝色", "size": "笔袋", "missing": ["单买价"]}],
    )
    assert detail == "BD022A规格「蓝色/笔袋」缺单买价"


def test_build_validation_detail_for_validation_errors():
    detail = build_validation_detail(
        merchant_code="BD199A",
        page_errors=[
            {"type": "field", "field": "发货地", "message": "请选择发货地"},
            {"type": "inline", "field": "商品属性", "message": "材质不能为空"},
        ],
        preview_gaps=[{"style": "黄色", "size": "笔袋", "spec_code": "BD199A"}],
    )
    assert detail.startswith("BD199A")
    assert "发货地：请选择发货地" in detail
    assert "材质不能为空" in detail
    assert "缺规格预览图" in detail


def test_format_validation_detail_brief_joins_multiple():
    brief = ListingErrors.format_validation_detail_brief(
        [
            "规格「蓝色/笔袋」缺库存",
            "规格「蓝色/笔袋+挂件」缺拼团价",
            "页面提示：请完善商品属性",
        ],
        merchant_code="BD022A",
        max_items=2,
    )
    assert brief == "BD022A1、规格「蓝色/笔袋」缺库存，2、规格「蓝色/笔袋+挂件」缺拼团价等3项"


def test_compact_feishu_line_prefers_validation_detail_over_generic_label():
    detail = "BD022A规格「蓝色/笔袋」缺库存、拼团价"
    line = ListingErrors.compact_feishu_line(
        detail,
        reason_code=ListingErrorCode.VALIDATION_INCOMPLETE,
        merchant_code="BD022A",
    )
    assert line == detail
    assert line != ListingErrors.FEISHU_LABELS[ListingErrorCode.VALIDATION_INCOMPLETE]


def test_compact_feishu_line_prefers_validation_errors_detail():
    detail = "BD199A规格「黄色/笔袋」拼单价不能为空，规格「黄色/笔袋+挂件」缺规格预览图"
    line = ListingErrors.compact_feishu_line(
        detail,
        reason_code=ListingErrorCode.VALIDATION_ERRORS,
        merchant_code="BD199A",
    )
    assert line == detail
    assert line != ListingErrors.FEISHU_LABELS[ListingErrorCode.VALIDATION_ERRORS]


def test_format_brief_listing_failure_reason_validation_incomplete_detail():
    text = _format_brief_listing_failure_reason(
        listing_label="BD022A音乐小猫笔袋/第一套图",
        reason_code=ListingErrorCode.VALIDATION_INCOMPLETE,
        message="BD022A规格「蓝色/笔袋」缺库存、拼团价",
        merchant_code="BD022A",
    )
    assert text == "BD022A规格「蓝色/笔袋」缺库存、拼团价"


def test_format_brief_listing_failure_reason_validation_errors_detail():
    text = _format_brief_listing_failure_reason(
        listing_label="BD199A/第一套图",
        reason_code=ListingErrorCode.VALIDATION_ERRORS,
        message="BD199A品牌：请填写品牌，规格「黄色/笔袋」拼单价不能为空",
        merchant_code="BD199A",
    )
    assert "请填写品牌" in text
    assert "拼单价不能为空" in text

"""飞书失败原因短格式。"""

from pdd_agent.domain.listing_errors import ListingErrors


def test_format_numbered_joins_multiple_lines():
    text = ListingErrors.format_numbered(
        ["BD001控价区间为空", "BD002定价为空"],
    )
    assert text == "1、BD001控价区间为空，2、BD002定价为空"


def test_compact_catalog_subcode_line():
    line = ListingErrors.compact_feishu_line(
        "BD736A/第一套图：子编码 BD736B 控价区间数据缺失",
        merchant_code="BD736A",
    )
    assert line == "BD736B控价区间为空"


def test_compact_slot_mismatch_strips_prefix():
    line = ListingErrors.compact_feishu_line("兄弟款规格不齐：BD716A缺YKL004（应为5个）")
    assert line == "BD716A缺YKL004"

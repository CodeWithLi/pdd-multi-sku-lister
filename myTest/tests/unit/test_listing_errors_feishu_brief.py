"""飞书失败原因短格式。"""

from pdd_agent.domain.listing_errors import ListingErrors


def test_format_numbered_joins_multiple_lines():
    text = ListingErrors.format_numbered(
        ["BD001控价上限为空", "BD002定价为空"],
    )
    assert text == "1、BD001控价上限为空，2、BD002定价为空"


def test_compact_catalog_subcode_line():
    line = ListingErrors.compact_feishu_line(
        "BD736A/第一套图：子编码 BD736B PDD控价上限没数据",
        merchant_code="BD736A",
    )
    assert line == "BD736B控价上限为空"


def test_feishu_catalog_line_specific_aspects():
    assert (
        ListingErrors.feishu_catalog_line("BD021A卡皮巴拉笔袋", "pricing_missing")
        == "BD021A卡皮巴拉笔袋定价为空"
    )
    assert (
        ListingErrors.feishu_catalog_line("BD021A卡皮巴拉笔袋", "control_missing")
        == "BD021A卡皮巴拉笔袋控价为空"
    )
    assert (
        ListingErrors.feishu_catalog_line("BD021A卡皮巴拉笔袋", "range_min_missing")
        == "BD021A卡皮巴拉笔袋控价下限为空"
    )
    assert (
        ListingErrors.feishu_catalog_line("BD021A卡皮巴拉笔袋", "range_max_missing")
        == "BD021A卡皮巴拉笔袋控价上限为空"
    )
    assert (
        ListingErrors.feishu_catalog_line("BD021A卡皮巴拉笔袋", "feishu_row_not_found")
        == "BD021A卡皮巴拉笔袋飞书无此行"
    )
    assert (
        ListingErrors.feishu_catalog_line(
            "YKL001N",
            "subcode_missing",
            merchant_code="BD736B笔袋",
            is_sub=True,
        )
        == "BD736B笔袋缺YKL001N"
    )


def test_compact_rewrites_vague_product_table_message():
    line = ListingErrors.compact_feishu_line("BD021A卡皮巴拉笔袋商品表为空")
    assert line == "BD021A卡皮巴拉笔袋飞书无此行"

    line2 = ListingErrors.compact_feishu_line("BD021A卡皮巴拉笔袋商品表没数据")
    assert line2 == "BD021A卡皮巴拉笔袋飞书无此行"

    line3 = ListingErrors.compact_feishu_line("BD032A樱桃蛋糕笔袋定价没数据")
    assert line3 == "BD032A樱桃蛋糕笔袋定价为空"


def test_compact_slot_mismatch_strips_prefix():
    line = ListingErrors.compact_feishu_line("兄弟款规格不齐：BD716A缺YKL004（应为5个）")
    assert line == "BD716A缺YKL004"


def test_sanitize_feishu_failure_reason_strips_platform_markers():
    assert (
        ListingErrors.sanitize_feishu_failure_reason("BD023B毛绒小猫笔袋拼多多定价为空")
        == "BD023B毛绒小猫笔袋定价为空"
    )
    assert (
        ListingErrors.sanitize_feishu_failure_reason("BD685BPDD控价下限为空")
        == "BD685B控价下限为空"
    )
    assert (
        ListingErrors.sanitize_feishu_failure_reason(
            "1、BD716A拼多多定价为空，2、YKL001N拼多多控价为空"
        )
        == "1、BD716A定价为空，2、YKL001N控价为空"
    )

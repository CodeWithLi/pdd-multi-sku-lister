"""飞书失败原因短格式。"""

from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors


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
        == "BD021A卡皮巴拉笔袋零售综合成本为空"
    )
    assert (
        ListingErrors.feishu_catalog_line("BD021A卡皮巴拉笔袋", "range_max_missing")
        == "BD021A卡皮巴拉笔袋零售综合成本为空"
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
        == "YKL001N飞书无此行"
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


def test_compact_slot_mismatch_misnamed_preview_strips_prefix():
    line = ListingErrors.compact_feishu_line(
        "兄弟款规格图命名错误：BD046A有规格图未以BD046A开头（BD046B+YKL031D）（应为5个）"
    )
    assert line == "BD046A有规格图未以BD046A开头（BD046B+YKL031D）"


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


def test_build_preflight_no_skus_system_reason_includes_warnings_and_counts():
    preflight = {
        "units": [
            {
                "listing_label": "BD037B奶油泡芙笔袋/第一套图",
                "warnings": [
                    "[BD037B奶油泡芙笔袋/第一套图] 目录「BD037B奶油泡芙笔袋」无规格预览图（需非数字命名的 png/jpg）",
                    "[BD037B奶油泡芙笔袋/第一套图] 未解析到任何有效 SKU",
                ],
                "carousel_images": ["1.png", "2.png"],
                "detail_images": [],
            }
        ],
        "issues": [],
    }
    text = ListingErrors.build_preflight_no_skus_system_reason(
        preflight,
        "BD037B奶油泡芙笔袋/第一套图",
    )
    assert "无规格预览图" in text
    assert "主图 2 张" in text
    assert "未解析到任何有效 SKU" not in text
    assert "飞书无数据或名称未匹配" in text


def test_infer_no_sku_failure_brief_points_to_combo_subcode():
    preflight = {
        "units": [
            {
                "listing_label": "AXBD001A/第一套图",
                "warnings": [
                    "[AXBD001A/第一套图] 组合图[AXBD001A+AXBD001B]商品表无子编码[AXBD001B]，不上架 AXBD001B.png",
                ],
            }
        ]
    }
    brief = ListingErrors.infer_no_sku_failure_brief(
        preflight=preflight,
        listing_label="AXBD001A/第一套图",
        merchant_code="AXBD001A",
    )
    assert brief == "AXBD001A下子图AXBD001A+AXBD001B飞书无此行"


def test_infer_no_sku_failure_brief_pricing_missing_on_subcode():
    preflight = {
        "units": [
            {
                "listing_label": "AXBD001A/第一套图",
                "warnings": [
                    "[AXBD001A/第一套图] 组合图[AXBD001A+AXBD001B]商品表无编码[AXBD001B]，无法定价",
                ],
            }
        ]
    }
    brief = ListingErrors.infer_no_sku_failure_brief(
        preflight=preflight,
        listing_label="AXBD001A/第一套图",
        merchant_code="AXBD001A",
    )
    assert brief == "AXBD001A下子图AXBD001A+AXBD001B的定价为空"


def test_infer_no_sku_failure_brief_bd349a_combo_subimage():
    preflight = {
        "units": [
            {
                "listing_label": "BD349A/第一套图",
                "warnings": [
                    "[BD349A/第一套图] 组合图[BD349A+PS004A小白鲨]商品表无编码[PS004A小白鲨]，无法定价",
                ],
            }
        ]
    }
    brief = ListingErrors.infer_no_sku_failure_brief(
        preflight=preflight,
        listing_label="BD349A/第一套图",
        merchant_code="BD349A",
    )
    assert brief == "BD349A下子图BD349A+PS004A小白鲨的定价为空"


def test_infer_no_sku_failure_brief_legacy_warning_without_combo_stem():
    preflight = {
        "units": [
            {
                "listing_label": "AXBD001A/第一套图",
                "warnings": [
                    "[AXBD001A/第一套图] 商品表无编码[AXBD001B]，无法定价",
                ],
            }
        ]
    }
    brief = ListingErrors.infer_no_sku_failure_brief(
        preflight=preflight,
        listing_label="AXBD001A/第一套图",
        merchant_code="AXBD001A",
    )
    assert brief == "AXBD001A下子图AXBD001B的定价为空"


def test_compact_feishu_line_parses_catalog_warning():
    line = ListingErrors.compact_feishu_line(
        "[BD027A/第一套图] 商品表无子编码[BD027B]，不上架 preview.png",
        merchant_code="BD027A",
    )
    assert line == "BD027A下子图BD027B飞书无此行"


def test_compact_system_diagnostic_strips_leading_brackets():
    raw = "[BD037B/第一套图][BD037B] 商品表无编码[BD037B]，不上架 x.png"
    compact = ListingErrors.compact_system_diagnostic(raw)
    assert compact.startswith("商品表无编码")
    assert "[BD037B/第一套图]" not in compact


def test_feishu_brief_detail_and_material_missing():
    detail = ListingErrors.compact_feishu_line(
        "[BD046A/第一套图] 未找到 6-8 详情图",
        merchant_code="BD046A",
    )
    assert detail == "BD046A详情图缺失"
    material = ListingErrors.compact_feishu_line(
        "[BD046A/第一套图] 未找到 9 商品素材图",
        merchant_code="BD046A",
    )
    assert material == "BD046A商品素材图缺失"


def test_feishu_brief_preview_file_size_rejected():
    line = ListingErrors.compact_feishu_line(
        "预览图大小不能超过3MB [绿色 / 笔袋]：上传图片大小不能超过 3MB",
        merchant_code="BD201A",
    )
    assert line == "BD201A预览图大小不能超过3MB"

    by_code = ListingErrors.compact_feishu_line(
        "",
        reason_code=ListingErrorCode.PREVIEW_IMAGE_FILE_SIZE_REJECTED,
        merchant_code="BD201A",
    )
    assert by_code == "预览图大小不能超过3MB"

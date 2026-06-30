"""multi_spec_page 辅助逻辑单元测试。"""

import json

from pdd_agent.skills.listing import multi_spec_page as msp


def test_parse_scroll_find_result_ok():
    raw = json.dumps({"found": True, "idx": 9})
    assert msp._parse_scroll_find_result(raw) == 9


def test_parse_scroll_find_result_missing():
    assert msp._parse_scroll_find_result(json.dumps({"found": False, "idx": -1})) is None
    assert msp._parse_scroll_find_result(None) is None


def test_spec_order_row_index():
    styles = ["灰色", "黑色", "绿色"]
    sizes = ["笔袋+挂件", "笔袋+套装"]
    assert msp._spec_order_row_index("绿色", "笔袋+套装", styles, sizes) == 5


def test_scroll_js_blocks_are_composed():
    assert "scrollFindStyleSizeRow" in msp._SCROLL_FIND_STYLE_SIZE_ROW_JS
    assert "countKnownSpecRows" in msp._SCROLL_LOAD_ALL_ROWS_JS
    assert "prepareSkuTableForFill" in msp._STAMP_GLOBAL_ROW_INDICES_JS
    assert "stampGlobalRowIndices" in msp._STAMP_ROWS_BY_SCROLL_JS
    assert "getRowBySpec" in msp._RESOLVE_PREVIEW_INPUT_BY_SPEC_JS
    assert "getRowBySpec" in msp._FILL_ONE_BY_STYLE_SIZE_JS
    assert "verifyRowFilledBySpec" in msp._VERIFY_ROW_FILLED_BY_SPEC_JS
    assert "isValidSpecPair" in msp._STYLE_SIZE_MAP_JS
    assert "parseRowStyleSize" in msp._STYLE_SIZE_MAP_JS
    assert "getAllDataRows" in msp._FILL_ONE_BY_STYLE_SIZE_JS
    assert "rowValuesMatch" in msp._JS_FILL_HELPERS
    assert "verifyRowFilledBySpecValues" in msp._VERIFY_ROW_VALUES_BY_SPEC_JS


def test_style_size_map_allows_same_label_for_style_and_size():
    """主款尺寸槽与款式同名（如 BD014A）时仍应识别为有效规格对。"""
    js = msp._STYLE_SIZE_MAP_JS
    assert "style !== rowSize" not in js
    assert "isValidSpecPair" in js
    assert "classifySpecCellText" in js
    assert "rowMatchesSpec" in js
    assert "resolveRowSpecItem" in js


def test_rowspan_carry_style_for_row_match():
    """单颜色 rowspan 时，第 2+ 行只有尺寸列，匹配仍需继承上方颜色。"""

    def resolve_row_spec(idx, rows, style_names, size_names):
        parsed = []
        current_style = ""
        for row_i, cells in enumerate(rows[: idx + 1]):
            row_style = ""
            row_size = ""
            for text, has_rowspan in cells:
                if not text:
                    continue
                in_style = text in style_names
                in_size = text in size_names
                if in_style and in_size:
                    if row_style and text == row_style:
                        row_size = text
                    elif has_rowspan:
                        row_style = text
                        current_style = text
                    elif not row_style:
                        row_style = text
                    else:
                        row_size = text
                elif in_style:
                    row_style = text
                    if has_rowspan:
                        current_style = text
                elif in_size:
                    row_size = text
            style = row_style or current_style
            if style and row_size:
                parsed.append({"i": row_i, "style": style, "size": row_size})
        for item in reversed(parsed):
            if item["i"] == idx:
                return item
        return parsed[-1] if parsed else None

    style_names = ["蓝色"]
    size_names = ["笔袋", "笔袋+挂件", "笔袋+套尺"]
    rows = [
        [("蓝色", True), ("笔袋", False)],
        [("笔袋+挂件", False)],
        [("笔袋+套尺", False)],
    ]
    assert resolve_row_spec(0, rows, style_names, size_names) == {
        "i": 0,
        "style": "蓝色",
        "size": "笔袋",
    }
    assert resolve_row_spec(1, rows, style_names, size_names) == {
        "i": 1,
        "style": "蓝色",
        "size": "笔袋+挂件",
    }
    assert resolve_row_spec(2, rows, style_names, size_names) == {
        "i": 2,
        "style": "蓝色",
        "size": "笔袋+套尺",
    }


def test_row_vals_json_from_sku():
    from types import SimpleNamespace
    from pdd_agent.skills.listing.multi_spec_page import _row_data_from_sku, _row_vals_json

    sku = SimpleNamespace(
        inventory="10",
        group_price="29.9",
        single_price="30.9",
        combo_folder="BD022A音乐小猫笔袋+YKL001N",
    )
    data = _row_data_from_sku(sku, {})
    assert json.loads(_row_vals_json(data)) == [
        "10",
        "29.9",
        "30.9",
        "BD022A音乐小猫笔袋+YKL001N",
    ]


def test_add_style_specs_prefers_color_dimension():
    doc = msp.add_style_and_model_specs.__doc__ or ""
    assert "颜色" in doc


def test_prefer_style_size_fill_single_style():
    assert msp._prefer_style_size_fill(["BD025A面包小狗笔袋"], ["A", "B", "C"]) is True
    assert msp._prefer_style_size_fill(["款1", "款2"], ["M", "L"]) is False


def test_classify_spec_cell_same_label_logic():
    """款式=尺寸同名时：第一列(style+rowspan)=style，第二列同文案=size。"""

    def classify(text, has_rowspan, found_style, style_names, size_names):
        in_style = text in style_names
        in_size = text in size_names
        if in_style and in_size:
            if found_style and text == found_style:
                return "size"
            if has_rowspan:
                return "style"
            if not found_style:
                return "style"
            return "size"
        if in_style:
            return "style"
        if in_size:
            return "size"
        return None

    label = "BD025A面包小狗笔袋"
    styles = [label]
    sizes = [label, "YKL001M", "YKL004Q"]
    assert classify(label, True, "", styles, sizes) == "style"
    assert classify(label, False, label, styles, sizes) == "size"
    assert classify("YKL001M", False, label, styles, sizes) == "size"

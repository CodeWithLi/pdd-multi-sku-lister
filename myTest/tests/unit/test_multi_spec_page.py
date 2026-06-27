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
    assert "countStyleSizeRows" in msp._SCROLL_LOAD_ALL_ROWS_JS
    assert "stampGlobalRowIndices" in msp._STAMP_GLOBAL_ROW_INDICES_JS
    assert "getRowBySpec" in msp._RESOLVE_PREVIEW_INPUT_BY_SPEC_JS
    assert "getAllDataRows" in msp._FILL_ONE_BY_STYLE_SIZE_JS

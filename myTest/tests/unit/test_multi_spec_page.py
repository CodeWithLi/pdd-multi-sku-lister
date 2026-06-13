"""multi_spec_page 辅助逻辑单元测试。"""

import json

from pdd_agent.skills.listing import multi_spec_page as msp


def test_parse_scroll_find_result_ok():
    raw = json.dumps({"found": True, "idx": 9})
    assert msp._parse_scroll_find_result(raw) == 9


def test_parse_scroll_find_result_missing():
    assert msp._parse_scroll_find_result(json.dumps({"found": False, "idx": -1})) is None
    assert msp._parse_scroll_find_result(None) is None


def test_scroll_js_blocks_are_composed():
    assert "scrollFindStyleSizeRow" in msp._SCROLL_FIND_STYLE_SIZE_ROW_JS
    assert "countStyleSizeRows" in msp._SCROLL_LOAD_ALL_ROWS_JS
    assert "getAllDataRows" in msp._FILL_ONE_BY_STYLE_SIZE_JS

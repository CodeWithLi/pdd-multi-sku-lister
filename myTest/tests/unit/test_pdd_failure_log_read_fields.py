"""失败日志字段解析测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.field_display import (
    encode_cycle_relist_write_value,
    format_single_select,
)
from pdd_agent.integrations.feishu.pdd_failure_log_read import resolve_cycle_relist_field_name


def test_format_single_select_empty():
    assert format_single_select(None) == ""
    assert format_single_select("") == ""


def test_format_single_select_string():
    assert format_single_select("是") == "是"


def test_format_single_select_bool_checkbox():
    assert format_single_select(False) == ""
    assert format_single_select(True) == "是"
    assert format_single_select("False") == ""
    assert format_single_select("True") == "是"


def test_encode_cycle_relist_write_value_checkbox():
    meta = {
        "type": 3,
        "ui_type": "Checkbox",
        "property": {"options": [{"name": "是"}]},
    }
    assert encode_cycle_relist_write_value("", meta) is False
    assert encode_cycle_relist_write_value("循环上架中", meta) is True
    assert encode_cycle_relist_write_value("是", meta) == "是"


def test_resolve_cycle_relist_field_name_prefers_configured():
    fields = [
        {"field_name": "是否已循环上架", "type": 3},
        {"field_name": "其他", "type": 1},
    ]
    assert resolve_cycle_relist_field_name("是否已循环上架", fields) == "是否已循环上架"


def test_resolve_cycle_relist_field_name_fuzzy_match():
    fields = [
        {"field_name": "是否已循环上架", "type": 3},
    ]
    assert resolve_cycle_relist_field_name("是否循环上架", fields) == "是否已循环上架"

"""飞书字段名解析单元测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.bitable import (
    FIELD_MULTI_SELECT,
    FIELD_SINGLE_SELECT,
    clear_table_field_caches,
    coerce_field_value_for_table,
    map_fields_to_table_names,
    resolve_table_field_name,
)


class _FakeClient:
    pass


def test_resolve_table_field_name_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.bitable.list_fields",
        lambda client, app_token, table_id: [
            {"field_name": "商品ID", "type": 1},
            {"field_name": "宝贝标题", "type": 1},
        ],
    )
    clear_table_field_caches()

    resolved = resolve_table_field_name(_FakeClient(), "app", "tbl", "商品id")
    assert resolved == "商品ID"


def test_coerce_field_value_for_multi_select_wraps_string():
    value = coerce_field_value_for_table(
        "已上架",
        field_type=FIELD_MULTI_SELECT,
        field_property={"options": [{"name": "已上架"}, {"name": "报错上架失败"}]},
    )
    assert value == ["已上架"]


def test_map_fields_to_table_names_coerces_multi_select_status(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.bitable.list_fields",
        lambda client, app_token, table_id: [
            {"field_name": "状态", "type": FIELD_MULTI_SELECT, "property": {"options": [{"name": "已上架"}]}},
            {"field_name": "商品ID", "type": 1},
        ],
    )
    clear_table_field_caches()

    mapped = map_fields_to_table_names(
        _FakeClient(),
        "app",
        "tbl",
        {"状态": "已上架", "商品ID": "967336943667"},
    )
    assert mapped["状态"] == ["已上架"]
    assert mapped["商品ID"] == "967336943667"


def test_coerce_field_value_for_single_select_keeps_string():
    value = coerce_field_value_for_table(
        "成功",
        field_type=FIELD_SINGLE_SELECT,
        field_property={"options": [{"name": "成功"}, {"name": "失败"}]},
    )
    assert value == "成功"

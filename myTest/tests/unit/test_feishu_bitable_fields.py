"""飞书字段名解析单元测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.bitable import resolve_table_field_name


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
    monkeypatch.setattr("pdd_agent.integrations.feishu.bitable._FIELD_LOOKUP_CACHE", {})

    resolved = resolve_table_field_name(_FakeClient(), "app", "tbl", "商品id")
    assert resolved == "商品ID"

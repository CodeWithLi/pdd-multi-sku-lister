"""飞书多维表格（Bitable）表 / 字段 / 记录操作。"""

from __future__ import annotations

from typing import Any

from pdd_agent.integrations.feishu.client import FeishuClient

# 字段类型：https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-field/guide
FIELD_TEXT = 1
FIELD_NUMBER = 2
FIELD_SINGLE_SELECT = 3
FIELD_DATETIME = 5
FIELD_URL = 15


def list_tables(client: FeishuClient, app_token: str) -> list[dict[str, Any]]:
    data = client.request(
        "GET",
        f"/bitable/v1/apps/{app_token}/tables",
        params={"page_size": 100},
    )
    return list(data.get("data", {}).get("items") or [])


def find_table_id_by_name(client: FeishuClient, app_token: str, name: str) -> str:
    for item in list_tables(client, app_token):
        if str(item.get("name") or "") == name:
            return str(item.get("table_id") or "")
    return ""


def create_table(client: FeishuClient, app_token: str, name: str) -> str:
    data = client.request(
        "POST",
        f"/bitable/v1/apps/{app_token}/tables",
        json={"table": {"name": name}},
    )
    table_id = str(data.get("data", {}).get("table_id") or "")
    if not table_id:
        raise RuntimeError(f"创建表失败: {name}")
    return table_id


def list_fields(client: FeishuClient, app_token: str, table_id: str) -> list[dict[str, Any]]:
    data = client.request(
        "GET",
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        params={"page_size": 100},
    )
    return list(data.get("data", {}).get("items") or [])


def create_field(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    *,
    field_name: str,
    field_type: int,
    property: dict[str, Any] | None = None,
) -> str:
    body: dict[str, Any] = {"field_name": field_name, "type": field_type}
    if property:
        body["property"] = property
    data = client.request(
        "POST",
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        json=body,
    )
    field_id = str(data.get("data", {}).get("field", {}).get("field_id") or "")
    return field_id


def ensure_fields(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    field_defs: list[dict[str, Any]],
) -> None:
    existing = {str(item.get("field_name") or "") for item in list_fields(client, app_token, table_id)}
    for item in field_defs:
        name = str(item["field_name"])
        if name in existing:
            continue
        create_field(
            client,
            app_token,
            table_id,
            field_name=name,
            field_type=int(item["type"]),
            property=item.get("property"),
        )


def batch_create_records(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    records: list[dict[str, Any]],
) -> list[str]:
    if not records:
        return []
    data = client.request(
        "POST",
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
        json={"records": [{"fields": fields} for fields in records]},
    )
    created = data.get("data", {}).get("records") or []
    return [str(item.get("record_id") or "") for item in created]


_FIELD_LOOKUP_CACHE: dict[tuple[str, str], dict[str, str]] = {}


def _table_field_lookup(client: FeishuClient, app_token: str, table_id: str) -> dict[str, str]:
    key = (app_token, table_id)
    cached = _FIELD_LOOKUP_CACHE.get(key)
    if cached is not None:
        return cached
    fields = list_fields(client, app_token, table_id)
    lookup = {
        str(item.get("field_name") or ""): str(item.get("field_name") or "")
        for item in fields
        if str(item.get("field_name") or "").strip()
    }
    _FIELD_LOOKUP_CACHE[key] = lookup
    return lookup


def resolve_table_field_name(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    configured_name: str,
) -> str:
    """将配置中的列名解析为飞书表内真实列名（大小写不敏感兜底）。"""
    name = str(configured_name or "").strip()
    if not name:
        return ""
    lookup = _table_field_lookup(client, app_token, table_id)
    if name in lookup:
        return name
    for real_name in lookup:
        if real_name.lower() == name.lower():
            return real_name
    return name


def search_records_by_field(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    *,
    field_name: str,
    value: str,
    page_size: int = 20,
) -> list[dict[str, Any]]:
    """按单字段精确匹配查已有记录（用于幂等去重）。"""
    resolved_name = resolve_table_field_name(client, app_token, table_id, field_name)
    body = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": resolved_name,
                    "operator": "is",
                    "value": [value],
                }
            ],
        },
        "page_size": page_size,
    }
    data = client.request(
        "POST",
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
        json=body,
    )
    return list(data.get("data", {}).get("items") or [])


def map_fields_to_table_names(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """把 fields 的 key 映射为飞书表真实列名。"""
    mapped: dict[str, Any] = {}
    for key, value in fields.items():
        mapped[resolve_table_field_name(client, app_token, table_id, key)] = value
    return mapped

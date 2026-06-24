"""飞书多维表格（Bitable）表 / 字段 / 记录操作。"""

from __future__ import annotations

from typing import Any

from pdd_agent.integrations.feishu.client import FeishuClient

# 字段类型：https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-field/guide
FIELD_TEXT = 1
FIELD_NUMBER = 2
FIELD_SINGLE_SELECT = 3
FIELD_MULTI_SELECT = 4
FIELD_DATETIME = 5
FIELD_URL = 15
FIELD_WORKFLOW = 24


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


def list_views(client: FeishuClient, app_token: str, table_id: str) -> list[dict[str, Any]]:
    data = client.request(
        "GET",
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/views",
        params={"page_size": 100},
    )
    return list(data.get("data", {}).get("items") or [])


def find_view_id_by_name(client: FeishuClient, app_token: str, table_id: str, name: str) -> str:
    target = str(name or "").strip()
    if not target:
        return ""
    for item in list_views(client, app_token, table_id):
        if str(item.get("view_name") or item.get("name") or "").strip() == target:
            return str(item.get("view_id") or "")
    return ""


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


def batch_update_records(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    records: list[dict[str, Any]],
) -> list[str]:
    """批量更新记录。records 每项含 record_id + fields。"""
    if not records:
        return []
    payload = [
        {"record_id": str(item["record_id"]), "fields": dict(item["fields"] or {})}
        for item in records
        if str(item.get("record_id") or "").strip()
    ]
    if not payload:
        return []
    data = client.request(
        "POST",
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update",
        json={"records": payload},
    )
    updated = data.get("data", {}).get("records") or []
    return [str(item.get("record_id") or "") for item in updated]


_FIELD_LOOKUP_CACHE: dict[tuple[str, str], dict[str, str]] = {}
_TABLE_FIELD_META_CACHE: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}


def clear_table_field_caches() -> None:
    """测试或热更新表结构后清空字段缓存。"""
    _FIELD_LOOKUP_CACHE.clear()
    _TABLE_FIELD_META_CACHE.clear()


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


def get_table_field_meta(client: FeishuClient, app_token: str, table_id: str) -> dict[str, dict[str, Any]]:
    key = (app_token, table_id)
    cached = _TABLE_FIELD_META_CACHE.get(key)
    if cached is not None:
        return cached
    fields = list_fields(client, app_token, table_id)
    meta: dict[str, dict[str, Any]] = {}
    for item in fields:
        name = str(item.get("field_name") or "").strip()
        if not name:
            continue
        meta[name] = {
            "type": int(item.get("type") or 0),
            "property": item.get("property") if isinstance(item.get("property"), dict) else {},
        }
    _TABLE_FIELD_META_CACHE[key] = meta
    return meta


def _resolve_select_option(value: str, options: list[Any]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    names = [
        str(option.get("name") or "")
        for option in options
        if isinstance(option, dict) and str(option.get("name") or "").strip()
    ]
    if text in names:
        return text
    lowered = text.lower()
    for name in names:
        if name.lower() == lowered:
            return name
    return text


def coerce_field_value_for_table(
    value: Any,
    *,
    field_type: int,
    field_property: dict[str, Any] | None = None,
) -> Any:
    """按飞书列类型规范化写入值（单选/多选/链接等）。"""
    if value is None or value == "":
        return value
    prop = field_property or {}
    if field_type == FIELD_SINGLE_SELECT:
        options = prop.get("options") if isinstance(prop.get("options"), list) else []
        resolved = _resolve_select_option(str(value), options)
        return resolved or str(value).strip()
    if field_type == FIELD_MULTI_SELECT:
        options = prop.get("options") if isinstance(prop.get("options"), list) else []
        if isinstance(value, list):
            resolved_items = [
                _resolve_select_option(str(item), options) or str(item).strip()
                for item in value
                if str(item).strip()
            ]
            return [item for item in resolved_items if item]
        resolved = _resolve_select_option(str(value), options) or str(value).strip()
        return [resolved] if resolved else []
    if field_type == FIELD_URL:
        if isinstance(value, dict):
            link = str(value.get("link") or "").strip()
            if not link:
                return value
            text = str(value.get("text") or link).strip() or link
            return {"link": link, "text": text}
        text = str(value).strip()
        return {"link": text, "text": text} if text else value
    if field_type == FIELD_DATETIME:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            raw = value.strip()
            if raw.isdigit():
                return int(raw)
        return value
    if field_type == FIELD_NUMBER:
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        if not text:
            return value
        try:
            return float(text) if "." in text else int(text)
        except ValueError:
            return value
    return value


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


def resolve_table_field_name_from_candidates(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    candidates: tuple[str, ...] | list[str],
    configured_name: str = "",
) -> str:
    """按候选列名依次匹配飞书表真实列名（大小写不敏感）。"""
    names: list[str] = []
    configured = str(configured_name or "").strip()
    if configured:
        names.append(configured)
    for item in candidates:
        text = str(item or "").strip()
        if text and text not in names:
            names.append(text)
    if not names:
        return ""
    lookup = _table_field_lookup(client, app_token, table_id)
    for name in names:
        if name in lookup:
            return name
        for real_name in lookup:
            if real_name.lower() == name.lower():
                return real_name
    return names[0]


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


def search_records_by_field_values(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    *,
    field_name: str,
    values: list[str],
    view_id: str = "",
    page_size: int = 500,
    chunk_size: int = 50,
) -> list[dict[str, Any]]:
    """按字段多值 OR 精确匹配批量查记录（用于按商品编码拉取）。"""
    normalized = list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))
    if not normalized:
        return []

    resolved_name = resolve_table_field_name(client, app_token, table_id, field_name)
    items: list[dict[str, Any]] = []
    size = max(1, min(int(page_size), 500))
    step = max(1, min(int(chunk_size), 50))

    for start in range(0, len(normalized), step):
        chunk = normalized[start : start + step]
        conditions = [
            {
                "field_name": resolved_name,
                "operator": "is",
                "value": [value],
            }
            for value in chunk
        ]
        page_token = ""
        while True:
            body: dict[str, Any] = {
                "filter": {
                    "conjunction": "or",
                    "conditions": conditions,
                },
                "page_size": size,
            }
            if view_id:
                body["view_id"] = str(view_id)
            if page_token:
                body["page_token"] = page_token
            data = client.request(
                "POST",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                json=body,
            )
            payload = data.get("data") or {}
            batch = list(payload.get("items") or [])
            items.extend(batch)
            if not payload.get("has_more"):
                break
            page_token = str(payload.get("page_token") or "").strip()
            if not page_token:
                break
    return items


def search_records_by_field_contains(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    *,
    field_name: str,
    values: list[str],
    view_id: str = "",
    page_size: int = 500,
    chunk_size: int = 20,
) -> list[dict[str, Any]]:
    """按字段「包含」子串批量查记录（商品编码带中文后缀时用编码前缀匹配）。"""
    normalized = list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))
    if not normalized:
        return []

    resolved_name = resolve_table_field_name(client, app_token, table_id, field_name)
    items: list[dict[str, Any]] = []
    size = max(1, min(int(page_size), 500))
    step = max(1, min(int(chunk_size), 20))

    for start in range(0, len(normalized), step):
        chunk = normalized[start : start + step]
        conditions = [
            {
                "field_name": resolved_name,
                "operator": "contains",
                "value": [value],
            }
            for value in chunk
        ]
        page_token = ""
        while True:
            body: dict[str, Any] = {
                "filter": {
                    "conjunction": "or",
                    "conditions": conditions,
                },
                "page_size": size,
            }
            if view_id:
                body["view_id"] = str(view_id)
            if page_token:
                body["page_token"] = page_token
            data = client.request(
                "POST",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                json=body,
            )
            payload = data.get("data") or {}
            batch = list(payload.get("items") or [])
            items.extend(batch)
            if not payload.get("has_more"):
                break
            page_token = str(payload.get("page_token") or "").strip()
            if not page_token:
                break
    return items


def map_fields_to_table_names(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """把 fields 的 key 映射为飞书表真实列名，并按列类型规范化值。"""
    meta = get_table_field_meta(client, app_token, table_id)
    mapped: dict[str, Any] = {}
    for key, value in fields.items():
        resolved_name = resolve_table_field_name(client, app_token, table_id, key)
        field_meta = meta.get(resolved_name) or {}
        field_type = int(field_meta.get("type") or 0)
        field_property = field_meta.get("property") if isinstance(field_meta.get("property"), dict) else {}
        mapped[resolved_name] = coerce_field_value_for_table(
            value,
            field_type=field_type,
            field_property=field_property,
        )
    return mapped


def list_all_records(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    *,
    page_size: int = 500,
) -> list[dict[str, Any]]:
    """分页拉取表内全部记录。"""
    items: list[dict[str, Any]] = []
    page_token = ""
    size = max(1, min(int(page_size), 500))
    while True:
        params: dict[str, Any] = {"page_size": size}
        if page_token:
            params["page_token"] = page_token
        data = client.request(
            "GET",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            params=params,
        )
        payload = data.get("data") or {}
        batch = list(payload.get("items") or [])
        items.extend(batch)
        if not payload.get("has_more"):
            break
        page_token = str(payload.get("page_token") or "").strip()
        if not page_token:
            break
    return items

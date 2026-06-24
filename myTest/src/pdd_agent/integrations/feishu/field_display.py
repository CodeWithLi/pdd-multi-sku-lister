"""飞书多维表格字段值的展示与流程（Stage）字段解析。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def format_user_names(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("en_name") or "").strip()
                if name:
                    names.append(name)
            elif item:
                names.append(str(item))
        return "、".join(names)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("en_name") or "").strip()
    return str(value).strip()


def format_datetime_ms(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        ms = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y/%m/%d %H:%M")


def parse_workflow_stage(value: Any) -> dict[str, Any]:
    """解析流程（Stage, type=24）字段原始值。"""
    if value is None or value == "":
        return {
            "present": False,
            "label": "",
            "stage_id": "",
            "raw": None,
        }

    label = ""
    stage_id = ""

    if isinstance(value, str):
        label = value.strip()
    elif isinstance(value, dict):
        label = str(
            value.get("name")
            or value.get("text")
            or value.get("stage_name")
            or value.get("status")
            or ""
        ).strip()
        stage_id = str(value.get("id") or value.get("stage_id") or "").strip()
        if not label and isinstance(value.get("value"), list):
            nested = value.get("value")
            if nested and isinstance(nested[0], dict):
                label = str(nested[0].get("text") or nested[0].get("name") or "").strip()
    elif isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            label = str(first.get("name") or first.get("text") or "").strip()
            stage_id = str(first.get("id") or "").strip()
        else:
            label = str(first).strip()

    return {
        "present": bool(label or stage_id or value not in (None, "", [], {})),
        "label": label,
        "stage_id": stage_id,
        "raw": value,
    }


def format_plain_text(value: Any) -> str:
    """文本字段：API 可能返回 string 或 [{text, type}]。"""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
            elif item:
                parts.append(str(item).strip())
        return "、".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "").strip()
    return str(value).strip()


def resolve_process_status(*, mirror_text: str = "") -> dict[str, str]:
    """以「处理状态镜像」文本列为处理状态来源（由飞书自动化从流程字段同步）。"""
    mirror = str(mirror_text or "").strip()
    if mirror:
        return {"label": mirror, "source": "mirror_text"}
    return {"label": "未同步", "source": "empty"}

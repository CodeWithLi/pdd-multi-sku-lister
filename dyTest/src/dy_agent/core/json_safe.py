"""将嵌套结构转为 JSON 可序列化对象（落库 / API 用）。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any


def json_safe(value: Any, _seen: set[int] | None = None) -> Any:
    """递归转换 dict/list/dataclass/Pydantic/枚举等为 JSON 可写结构。"""
    seen = _seen if _seen is not None else set()

    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value), seen)

    if hasattr(value, "model_dump"):
        try:
            return json_safe(value.model_dump(mode="json"), seen)
        except TypeError:
            return json_safe(value.model_dump(), seen)

    if isinstance(value, dict):
        oid = id(value)
        if oid in seen:
            return None
        seen.add(oid)
        try:
            return {str(k): json_safe(v, seen) for k, v in value.items()}
        finally:
            seen.discard(oid)

    if isinstance(value, (list, tuple, set)):
        oid = id(value)
        if oid in seen:
            return None
        seen.add(oid)
        try:
            return [json_safe(v, seen) for v in value]
        finally:
            seen.discard(oid)

    return str(value)

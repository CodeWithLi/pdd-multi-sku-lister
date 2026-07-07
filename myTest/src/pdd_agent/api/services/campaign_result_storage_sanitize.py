"""
Campaign run 结果 — 落库前 JSON 安全化。

与 task_runner._json_safe 解耦：剔除 Playwright Page 等不可序列化对象。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

_NON_JSON_TYPE_NAMES = frozenset(
    {
        "Page",
        "Frame",
        "Locator",
        "Browser",
        "BrowserContext",
        "ElementHandle",
        "JSHandle",
        "Response",
        "Request",
        "DpPage",
    }
)


def _sanitize_leaf(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            pass
    type_name = type(value).__name__
    if type_name in _NON_JSON_TYPE_NAMES:
        url = getattr(value, "url", None)
        if callable(url):
            try:
                return f"<{type_name} url={url()}>"
            except Exception:
                return f"<{type_name}>"
        return f"<{type_name}>"
    try:
        json.dumps(value)
        return value
    except TypeError:
        return f"<{type_name}>"


def sanitize_campaign_result_for_storage(value: Any, _seen: set[int] | None = None) -> Any:
    """递归清理 campaign graph 返回值，确保可写入 run_records.result JSON 列。"""
    seen = _seen if _seen is not None else set()
    if isinstance(value, dict):
        oid = id(value)
        if oid in seen:
            return None
        seen.add(oid)
        try:
            return {
                str(key): sanitize_campaign_result_for_storage(item, seen)
                for key, item in value.items()
            }
        finally:
            seen.discard(oid)
    if isinstance(value, list):
        oid = id(value)
        if oid in seen:
            return None
        seen.add(oid)
        try:
            return [sanitize_campaign_result_for_storage(item, seen) for item in value]
        finally:
            seen.discard(oid)
    return _sanitize_leaf(value)


def json_safe_campaign_result_for_storage(value: Any) -> Any:
    """先走 task_runner._json_safe，再剔除 Playwright 等残留对象。"""
    from pdd_agent.api.services.task_runner import _json_safe

    return sanitize_campaign_result_for_storage(_json_safe(value))

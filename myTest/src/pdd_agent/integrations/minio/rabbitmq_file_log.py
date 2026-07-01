"""RabbitMQ 专用文件日志：按自然日写入 data/rabbitmq_logs/YYYY-MM-DD.log。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from pdd_agent.paths import PROJECT_ROOT

_LOG_DIR = PROJECT_ROOT / "data" / "rabbitmq_logs"
_LOCK = threading.Lock()
_CURRENT_DATE = ""
_CURRENT_PATH: Path | None = None

# 事件类型（便于 grep）
EVENT_CONSUMER_START = "CONSUMER_START"
EVENT_CONSUMER_SKIP = "CONSUMER_SKIP"
EVENT_CONSUMER_CONNECTED = "CONSUMER_CONNECTED"
EVENT_CONSUMER_STOP = "CONSUMER_STOP"
EVENT_CONSUMER_ERROR = "CONSUMER_ERROR"
EVENT_MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
EVENT_MESSAGE_ACK = "MESSAGE_ACK"
EVENT_MESSAGE_NACK = "MESSAGE_NACK"
EVENT_DEBOUNCE_FLUSH = "DEBOUNCE_FLUSH"
EVENT_BATCH_START = "BATCH_START"
EVENT_BATCH_DONE = "BATCH_DONE"
EVENT_AUTO_PIPELINE = "AUTO_PIPELINE"
EVENT_SSE_PUSH = "SSE_PUSH"
EVENT_LOCAL_PROCESS = "LOCAL_PROCESS"
EVENT_SYNC_START = "SYNC_START"
EVENT_SYNC_DONE = "SYNC_DONE"
EVENT_SYNC_FAILED = "SYNC_FAILED"
EVENT_PIPELINE_START = "PIPELINE_START"
EVENT_PIPELINE_QUEUED = "PIPELINE_QUEUED"


def rabbitmq_log_dir() -> Path:
    return _LOG_DIR


def _log_path_for_today() -> Path:
    global _CURRENT_DATE, _CURRENT_PATH
    today = datetime.now().strftime("%Y-%m-%d")
    if today != _CURRENT_DATE or _CURRENT_PATH is None:
        _CURRENT_DATE = today
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        _CURRENT_PATH = _LOG_DIR / f"{today}.log"
    return _CURRENT_PATH


def _format_fields(fields: dict[str, Any]) -> str:
    if not fields:
        return ""
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
        if len(text) > 2000:
            text = f"{text[:2000]}...(共{len(text)}字)"
        parts.append(f"{key}={text}")
    return " | ".join(parts)


def log_rabbitmq_event(
    event: str,
    message: str = "",
    **fields: Any,
) -> None:
    """写入当日 RabbitMQ 日志文件（线程安全）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    detail = _format_fields(fields)
    line = f"{ts} [{event}]"
    if message:
        line = f"{line} {message}"
    if detail:
        line = f"{line} | {detail}"
    try:
        path = _log_path_for_today()
        with _LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # 文件日志失败不应影响消费
        pass


def summarize_auto_pipeline(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    out: dict[str, Any] = {
        "triggered": bool(result.get("triggered")),
        "reason": str(result.get("reason") or ""),
        "reason_label": str(result.get("reason_label") or ""),
        "trigger_mode": str(result.get("trigger_mode") or ""),
    }
    if result.get("product_codes"):
        out["product_codes"] = list(result.get("product_codes") or [])
    if result.get("append_sync_full_image_set"):
        out["append_sync_full_image_set"] = True
        out["synced_selectors"] = list(result.get("synced_selectors") or [])
    return out


def summarize_batch_groups(batch_summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in batch_summary.get("groups") or []:
        if not isinstance(group, dict):
            continue
        rows.append(
            {
                "change_type": group.get("change_type"),
                "change_label": group.get("change_label"),
                "selector": group.get("selector"),
                "product_code": group.get("product_code"),
                "file_count": group.get("file_count"),
                "path": group.get("path"),
            }
        )
    return rows

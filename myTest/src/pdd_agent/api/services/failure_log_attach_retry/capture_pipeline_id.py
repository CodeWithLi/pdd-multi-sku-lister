"""失败日志挂回原链路 — 「抓取链路 ID」闸门。

需与「挂回原链路」同时开启：从系统原因解析 pipeline_id，
有 ID 才继续处理，无 ID 则跳过。
"""

from __future__ import annotations

from typing import Any


def is_capture_pipeline_id_enabled(watch) -> bool:
    if watch is None:
        return False
    return bool(getattr(watch, "capture_pipeline_id_enabled", False))


def is_attach_source_pipeline_enabled_flag(watch) -> bool:
    if watch is None:
        return False
    return bool(getattr(watch, "attach_source_pipeline_enabled", False))


def is_attach_path_fully_enabled(watch) -> bool:
    """挂回原链路 + 抓取链路 ID 同时开启，才走新路径。"""
    return is_attach_source_pipeline_enabled_flag(watch) and is_capture_pipeline_id_enabled(watch)


def extract_captured_pipeline_id(candidate: dict[str, Any]) -> str:
    from pdd_agent.integrations.feishu.failure_log_pipeline_system_reason import (
        extract_pipeline_id_from_failure_log_item,
    )

    return str(extract_pipeline_id_from_failure_log_item(candidate) or "").strip()


def evaluate_capture_pipeline_id_gate(
    candidate: dict[str, Any],
    *,
    watch,
) -> dict[str, Any]:
    """
    返回:
      enabled=False → 未开抓取，不应走挂回闸门
      ok + pipeline_id → 可继续
      skipped + reason=missing_source_pipeline_id → 应跳过本条
    """
    if not is_capture_pipeline_id_enabled(watch):
        return {
            "enabled": False,
            "ok": False,
            "skipped": False,
            "pipeline_id": "",
            "reason": "capture_pipeline_id_disabled",
        }

    pipeline_id = ""
    try:
        pipeline_id = extract_captured_pipeline_id(candidate)
    except Exception:
        pipeline_id = ""

    if pipeline_id:
        return {
            "enabled": True,
            "ok": True,
            "skipped": False,
            "pipeline_id": pipeline_id,
            "reason": "",
        }

    return {
        "enabled": True,
        "ok": True,
        "skipped": True,
        "pipeline_id": "",
        "reason": "missing_source_pipeline_id",
    }

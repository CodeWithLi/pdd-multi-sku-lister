"""失败日志循环上架：轮询拉取与处理结果审计。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    create_failure_cycle_relist_action_log,
    create_failure_cycle_relist_poll_log,
)

logger = get_logger(__name__)


def record_cycle_relist_poll(
    *,
    polled_at: datetime | None = None,
    candidate_total: int = 0,
    new_count: int = 0,
    fetch_mode: str = "",
    fetch_page_size: int = 0,
    table_id: str = "",
    table_name: str = "",
    candidates: list[dict[str, Any]] | None = None,
    new_candidates: list[dict[str, Any]] | None = None,
) -> str:
    """记录一次轮询拉取的候选快照，返回 poll_log_id（无库时为空串）。"""
    try:
        row = create_failure_cycle_relist_poll_log(
            polled_at=polled_at,
            candidate_total=candidate_total,
            new_count=new_count,
            fetch_mode=fetch_mode,
            fetch_page_size=fetch_page_size,
            table_id=table_id,
            table_name=table_name,
            candidates=candidates,
            new_candidates=new_candidates,
        )
        return str(row.poll_log_id) if row else ""
    except Exception:
        logger.warning("record cycle relist poll failed", exc_info=True)
        return ""


def record_cycle_relist_action(
    *,
    record_id: str,
    merchant_code: str = "",
    account_name: str = "",
    account_id: str = "",
    failure_reason: str = "",
    report_platform: str = "",
    status: str,
    message: str = "",
    pipeline_id: str = "",
    trigger_source: str = "auto_watch",
    poll_log_id: str = "",
    action_at: datetime | None = None,
) -> None:
    """记录单条候选的处理结果（启动/跳过/失败）。"""
    try:
        create_failure_cycle_relist_action_log(
            feishu_record_id=record_id,
            merchant_code=merchant_code,
            account_name=account_name,
            account_id=account_id,
            failure_reason=failure_reason,
            report_platform=report_platform,
            status=status,
            message=message,
            pipeline_id=pipeline_id,
            trigger_source=trigger_source,
            poll_log_id=poll_log_id,
            action_at=action_at,
        )
    except Exception:
        logger.warning(
            "record cycle relist action failed record_id=%s status=%s",
            record_id,
            status,
            exc_info=True,
        )


def action_log_to_dict(row) -> dict[str, str]:
    action_at = row.action_at
    at_text = action_at.isoformat(timespec="seconds") if action_at else ""
    return {
        "at": at_text,
        "record_id": str(row.feishu_record_id or ""),
        "merchant_code": str(row.merchant_code or ""),
        "account_name": str(row.account_name or ""),
        "failure_reason": str(row.failure_reason or ""),
        "status": str(row.status or ""),
        "message": str(row.message or ""),
        "pipeline_id": str(row.pipeline_id or ""),
        "trigger_source": str(row.trigger_source or ""),
    }


def poll_log_to_dict(row) -> dict[str, Any]:
    polled_at = row.polled_at
    polled_text = polled_at.isoformat(timespec="seconds") if polled_at else ""
    return {
        "poll_log_id": str(row.poll_log_id or ""),
        "polled_at": polled_text,
        "candidate_total": int(row.candidate_total or 0),
        "new_count": int(row.new_count or 0),
        "fetch_mode": str(row.fetch_mode or ""),
        "fetch_page_size": int(row.fetch_page_size or 0),
        "table_id": str(row.table_id or ""),
        "table_name": str(row.table_name or ""),
        "candidates": list(row.candidates or []),
        "new_candidates": list(row.new_candidates or []),
    }

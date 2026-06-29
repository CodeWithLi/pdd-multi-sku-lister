"""失败日志循环上架：每日整合链路触发记录。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import create_daily_cycle_relist_record

logger = get_logger(__name__)


def record_cycle_relist_pipeline_started(
    outcome: dict[str, Any],
    *,
    trigger_source: str = "auto_watch",
) -> None:
    """飞书失败日志触发整合链路成功后写入每日统计。"""
    if not isinstance(outcome, dict):
        return
    if not outcome.get("ok") or bool(outcome.get("skipped")):
        return
    pipeline_id = str(outcome.get("pipeline_id") or "").strip()
    account_id = str(outcome.get("account_id") or "").strip()
    if not pipeline_id or not account_id:
        return
    try:
        create_daily_cycle_relist_record(
            feishu_record_id=str(outcome.get("record_id") or "").strip(),
            account_id=account_id,
            shop_display_name=resolve_account_display_name(account_id),
            merchant_code=str(outcome.get("merchant_code") or "").strip(),
            pipeline_id=pipeline_id,
            product_codes=[
                str(code).strip()
                for code in (outcome.get("product_codes") or [])
                if str(code).strip()
            ],
            report_platform=str(outcome.get("report_platform") or "").strip(),
            trigger_source=trigger_source,
            triggered_at=datetime.now(),
        )
    except Exception:
        logger.warning(
            "record daily cycle relist failed pipeline_id=%s record_id=%s",
            pipeline_id,
            outcome.get("record_id"),
            exc_info=True,
        )

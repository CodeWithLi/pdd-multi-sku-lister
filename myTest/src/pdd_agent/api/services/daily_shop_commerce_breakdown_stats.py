"""日报：按活动 ID / 推广拆分店铺运营链路成功数。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from pdd_agent.db.models import RunRecordORM, TaskQueueORM
from pdd_agent.db.repositories import (
    _count_success_items_from_run_result,
    summarize_promotion_success_between,
)
from pdd_agent.db.session import is_database_available, session_scope

ACTIVITY_618_ID = "20981"
ACTIVITY_DISCOUNT_ID = "21365"


def _summarize_activity_register_success_for_activity_id(
    *,
    start: datetime,
    end: datetime,
    activity_id: str,
    inclusive_end: bool = True,
) -> list[dict[str, str | int]]:
    """按店铺汇总指定活动 ID 的报名成功商品数。"""
    if not is_database_available():
        return []
    target_activity_id = str(activity_id or "").strip()
    if not target_activity_id:
        return []

    counts: dict[str, int] = defaultdict(int)
    with session_scope() as session:
        query = (
            session.query(TaskQueueORM, RunRecordORM)
            .join(RunRecordORM, TaskQueueORM.run_id == RunRecordORM.run_id)
            .filter(
                TaskQueueORM.status == "success",
                TaskQueueORM.agent == "campaign",
                TaskQueueORM.finished_at.isnot(None),
                TaskQueueORM.finished_at >= start,
            )
        )
        if inclusive_end:
            query = query.filter(TaskQueueORM.finished_at <= end)
        else:
            query = query.filter(TaskQueueORM.finished_at < end)

        for task, run in query.all():
            payload = task.payload if isinstance(task.payload, dict) else {}
            campaign_type = str(payload.get("campaign_type") or "marketing_activity_register").strip()
            if campaign_type != "marketing_activity_register":
                continue
            actual_activity_id = str(payload.get("activity_id") or "").strip()
            if actual_activity_id != target_activity_id:
                continue
            count = _count_success_items_from_run_result(
                run.result if isinstance(run.result, dict) else {},
                payload=payload,
            )
            if count <= 0:
                continue
            account_id = str(task.account_id or "").strip()
            counts[account_id] += count

    rows = [{"account_id": account_id, "count": count} for account_id, count in counts.items()]
    rows.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
    return rows


def summarize_activity_618_success_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[dict[str, str | int]]:
    return _summarize_activity_register_success_for_activity_id(
        start=start,
        end=end,
        activity_id=ACTIVITY_618_ID,
        inclusive_end=inclusive_end,
    )


def summarize_activity_discount_success_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[dict[str, str | int]]:
    return _summarize_activity_register_success_for_activity_id(
        start=start,
        end=end,
        activity_id=ACTIVITY_DISCOUNT_ID,
        inclusive_end=inclusive_end,
    )


def summarize_promotion_success_for_report(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[dict[str, str | int]]:
    return summarize_promotion_success_between(
        start=start,
        end=end,
        inclusive_end=inclusive_end,
    )


def rows_to_count_map(rows: list[dict[str, str | int]] | None) -> dict[str, int]:
    return {
        str(row.get("account_id") or "").strip(): int(row.get("count") or 0)
        for row in (rows or [])
        if str(row.get("account_id") or "").strip()
    }

"""
店铺运营状态 UI 与 DB 对账（启动 / 刷新 overview 时调用）。

UI「店铺运营状态」只读 account_lifecycle，不读 task_queue。
服务重启后 worker 会 requeue 中断任务（控制台继续跑），但 lifecycle 可能已被重置清掉或尚未补登记。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)


def refresh_commerce_overview_state(*, dispatch_pending: bool = False, dispatch_limit: int = 0) -> dict[str, Any]:
    """
    1. 清理残留 lifecycle
    2. 从活跃整合链路补登记 lifecycle（UI 可见）
    3. 可选派发排队意图
    """
    from pdd_agent.api.services.commerce_dispatch import (
        dispatch_all_pending_intents,
        reconcile_stale_lifecycles,
        sync_lifecycle_from_active_pipelines,
    )
    from pdd_agent.db.session import is_database_available

    if not is_database_available():
        return {"ok": False, "stale_cleared": 0, "synced": 0, "dispatched_count": 0}

    stale = reconcile_stale_lifecycles()
    synced = sync_lifecycle_from_active_pipelines()
    dispatched_count = 0
    if dispatch_pending and dispatch_limit > 0:
        dispatched_count = len(dispatch_all_pending_intents(limit=dispatch_limit))

    if stale or synced:
        logger.info(
            "commerce overview refreshed stale_cleared=%s lifecycle_synced=%s",
            stale,
            synced,
        )
    return {
        "ok": True,
        "stale_cleared": stale,
        "synced": synced,
        "dispatched_count": dispatched_count,
    }

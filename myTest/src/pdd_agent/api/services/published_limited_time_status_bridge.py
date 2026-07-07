"""
已发布商品 — 限时限量购状态桥接。

仅在 task_runner._schedule_feishu_limited_time_status 引用，限时限量购结束后写入每个商品状态。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.api.services.published_limited_time_status_resolver import (
    resolve_published_limited_time_statuses,
)
from pdd_agent.api.services.published_limited_time_status_store import (
    persist_published_limited_time_status_items,
)
from pdd_agent.core.logging import get_logger
from pdd_agent.domain.enums import RunStatus

logger = get_logger(__name__)


def persist_published_limited_time_status_after_run(
    *,
    account_id: str,
    selected_product_ids: list[str] | None,
    result: dict[str, Any] | None,
    status: RunStatus,
    run_id: str = "",
) -> dict[str, Any]:
    """限时限量购 run 结束后，将每个商品的成功/失败状态写入 published_products。"""
    try:
        items = resolve_published_limited_time_statuses(
            account_id=account_id,
            selected_product_ids=selected_product_ids,
            result=result,
            run_status=status,
            run_id=run_id,
        )
        if not items:
            logger.info(
                "published limited time status skip: no resolvable products account=%s run_id=%s",
                account_id,
                run_id,
            )
            return {"updated": 0, "skipped": 0, "failures": [], "resolved": 0}
        summary = persist_published_limited_time_status_items(items)
        summary["resolved"] = len(items)
        return summary
    except Exception:
        logger.exception(
            "persist published limited time status after run failed account=%s run_id=%s",
            account_id,
            run_id,
        )
        return {"updated": 0, "skipped": 0, "failures": [], "resolved": 0, "error": "persist_failed"}

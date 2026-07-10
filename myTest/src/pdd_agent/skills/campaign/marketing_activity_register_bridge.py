"""
营销活动报名 — 守卫版桥接入口。

仅在 Campaign Agent graph 引用，将搜索步骤替换为守卫版，不改动 register_marketing_activity 主体。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.config import AccountConfig
from pdd_agent.core.logging import get_logger
from pdd_agent.skills.campaign.marketing_activity_search_guard import search_marketing_activity_guarded

logger = get_logger(__name__)


def _bridge_log(account_id: str, message: str, **extra: Any) -> None:
    prefix = f"[{account_id}] [营销活动报名桥接]"
    parts = [f"{key}={value}" for key, value in extra.items() if value is not None and value != ""]
    line = f"{prefix} {message}"
    if parts:
        line = f"{line} | {' '.join(parts)}"
    logger.info(line)
    print(line, flush=True)


def register_marketing_activity_guarded(
    page: DpPage,
    account_id: str,
    activity_id: str,
    pdd_product_ids: list[str] | None = None,
    account: AccountConfig | None = None,
) -> dict[str, Any]:
    """调用原报名流程，临时将 search_marketing_activity 替换为守卫版。"""
    from pdd_agent.skills.campaign import marketing_activities as ma

    product_ids = list(pdd_product_ids or [])
    _bridge_log(
        account_id,
        "开始报名",
        activity_id=activity_id,
        product_count=len(product_ids),
        url=getattr(page, "url", ""),
    )

    original_search = ma.search_marketing_activity
    ma.search_marketing_activity = search_marketing_activity_guarded
    try:
        result = ma.register_marketing_activity(
            page,
            account_id,
            activity_id,
            pdd_product_ids=product_ids,
            account=account,
        )
    finally:
        ma.search_marketing_activity = original_search

    if isinstance(result, dict):
        result = dict(result)
        result["guarded_register"] = True

    status = str(result.get("status") or "")
    step = str(result.get("step") or "")
    error = str(result.get("error") or result.get("message") or "")
    if status == "success":
        _bridge_log(account_id, "报名完成", step=step, url=result.get("current_url") or getattr(page, "url", ""))
    else:
        _bridge_log(
            account_id,
            "报名失败，浏览器任务即将结束",
            status=status,
            step=step,
            error=error,
            url=result.get("current_url") or getattr(page, "url", ""),
        )
    return result


__all__ = [
    "register_marketing_activity_guarded",
    "search_marketing_activity_guarded",
]

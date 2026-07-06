"""
营销活动报名 — 守卫版桥接入口。

仅在 Campaign Agent graph 引用，将搜索步骤替换为守卫版，不改动 register_marketing_activity 主体。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.config import AccountConfig
from pdd_agent.skills.campaign.marketing_activity_search_guard import search_marketing_activity_guarded


def register_marketing_activity_guarded(
    page: DpPage,
    account_id: str,
    activity_id: str,
    pdd_product_ids: list[str] | None = None,
    account: AccountConfig | None = None,
) -> dict[str, Any]:
    """调用原报名流程，临时将 search_marketing_activity 替换为守卫版。"""
    from pdd_agent.skills.campaign import marketing_activities as ma

    original_search = ma.search_marketing_activity
    ma.search_marketing_activity = search_marketing_activity_guarded
    try:
        result = ma.register_marketing_activity(
            page,
            account_id,
            activity_id,
            pdd_product_ids=pdd_product_ids,
            account=account,
        )
    finally:
        ma.search_marketing_activity = original_search

    if isinstance(result, dict):
        result = dict(result)
        result["guarded_register"] = True
    return result


__all__ = [
    "register_marketing_activity_guarded",
    "search_marketing_activity_guarded",
]

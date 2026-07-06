"""
限时限量购 setup 入口 — 部分选品继续桥接。

仅在 setup_limited_time_campaign 引用，不改动 limited_time 内选品实现。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.campaign.limited_time_partial_selection import (
    narrow_scope_to_selected_products,
    select_campaign_products_allow_partial,
)


def run_product_selection_for_setup(
    page: DpPage,
    account_id: str,
    pdd_product_ids: list[str],
    mapping_ids: list[str],
) -> tuple[dict[str, Any], list[str], list[str], dict[str, Any]]:
    """
    执行选品（允许部分成功），并返回收窄后的商品 ID 供后续步骤使用。

    返回 (product_selection, effective_pdd_ids, effective_mapping_ids, partial_scope_meta)。
    """
    selection = select_campaign_products_allow_partial(page, account_id, pdd_product_ids)
    effective_pdd, effective_mapping, scope_meta = narrow_scope_to_selected_products(
        account_id,
        pdd_product_ids,
        mapping_ids,
        selection,
    )
    return selection, effective_pdd, effective_mapping, scope_meta

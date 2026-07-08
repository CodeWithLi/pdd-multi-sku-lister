"""库存下架 — 多店铺在售商品整合与聚水潭可用数分析。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.jushuitan_erp_inventory import load_jushuitan_inventory_map
from pdd_agent.inventory_delist.published_query import (
    PublishedCountSnapshot,
    count_published_by_account,
    erp_lookup_codes_for_items,
    list_on_sale_items,
)
from pdd_agent.inventory_delist.test_overrides import (
    apply_test_inventory_overrides,
    parse_test_inventory_overrides,
)

logger = get_logger(__name__)


@dataclass
class AccountProductBreakdown:
    account_id: str
    on_sale_codes: list[str] = field(default_factory=list)
    exclusive_codes: list[str] = field(default_factory=list)
    negative_inventory_codes: list[str] = field(default_factory=list)
    delist_candidate_codes: list[str] = field(default_factory=list)
    inventory_by_code: dict[str, int] = field(default_factory=dict)
    published_counts: PublishedCountSnapshot | None = None


@dataclass
class InventoryDelistAnalysis:
    account_ids: list[str]
    common_on_sale_codes: list[str] = field(default_factory=list)
    all_on_sale_codes: list[str] = field(default_factory=list)
    negative_inventory_codes: list[str] = field(default_factory=list)
    inventory_by_code: dict[str, int] = field(default_factory=dict)
    per_account: list[AccountProductBreakdown] = field(default_factory=list)
    feishu_query_count: int = 0
    feishu_called: bool = False
    feishu_rows_matched: int = 0
    feishu_force_refresh: bool = False
    feishu_error: str = ""
    database_available: bool = False
    test_override_enabled: bool = False
    test_overrides_applied: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _sorted_codes(codes: set[str]) -> list[str]:
    return sorted(codes, key=lambda c: c.casefold())


def _inventory_for_product_code(
    product_code: str,
    merchant_code: str,
    inventory_map: dict[str, int],
) -> int | None:
    """按商品编码优先、商家编码兜底匹配聚水潭可用数。"""
    for raw in (product_code, merchant_code):
        text = str(raw or "").strip()
        if not text:
            continue
        if text in inventory_map:
            return int(inventory_map[text])
        upper = text.upper()
        if upper in inventory_map:
            return int(inventory_map[upper])
    return None


def analyze_inventory_delist_targets(
    account_ids: list[str],
    *,
    force_feishu_refresh: bool = False,
    test_override_enabled: bool = False,
    test_inventory_overrides: dict[str, int] | None = None,
    test_override_text: str | None = None,
) -> InventoryDelistAnalysis:
    """整合多店铺在售编码，查询聚水潭可用数，找出可用数 < 0 的下架候选。"""
    from pdd_agent.db.session import is_database_available

    normalized_ids = list(dict.fromkeys(str(aid).strip() for aid in account_ids if str(aid).strip()))
    db_ok = is_database_available()

    per_account_items: dict[str, list] = {}
    per_account_sets: dict[str, set[str]] = {}
    count_snapshots: dict[str, PublishedCountSnapshot] = {}

    for aid in normalized_ids:
        counts = count_published_by_account(aid)
        count_snapshots[aid] = counts
        items = list_on_sale_items(aid)
        if not items and counts.on_sale_rows == 0 and counts.total_rows > counts.delisted_rows:
            # 兼容 status 非 on_sale 但仍在 published_products 的历史记录
            items = list_on_sale_items(aid, include_non_on_sale=True)
        per_account_items[aid] = items
        per_account_sets[aid] = {item.product_code for item in items}

    if not normalized_ids:
        return InventoryDelistAnalysis(
            account_ids=[],
            database_available=db_ok,
            diagnostics={"message": "未选择任何店铺"},
        )

    common = set.intersection(*per_account_sets.values()) if per_account_sets else set()
    all_codes = set().union(*per_account_sets.values()) if per_account_sets else set()

    erp_codes = erp_lookup_codes_for_items(
        [item for items in per_account_items.values() for item in items]
    )

    inventory_map: dict[str, int] = {}
    feishu_called = False
    feishu_rows_matched = 0
    feishu_error = ""

    if erp_codes:
        feishu_called = True
        try:
            inventory_map = load_jushuitan_inventory_map(
                codes=erp_codes,
                force_refresh=bool(force_feishu_refresh),
            )
            feishu_rows_matched = len(inventory_map)
            logger.info(
                "inventory delist feishu query accounts=%s product_codes=%s erp_codes=%s matched=%s force_refresh=%s",
                len(normalized_ids),
                len(all_codes),
                len(erp_codes),
                feishu_rows_matched,
                force_feishu_refresh,
            )
        except Exception as exc:
            feishu_error = str(exc)
            logger.exception("inventory delist feishu query failed")
    else:
        logger.warning(
            "inventory delist skip feishu: no on-sale published products accounts=%s snapshots=%s",
            normalized_ids,
            {aid: counts.on_sale_rows for aid, counts in count_snapshots.items()},
        )

    overrides = parse_test_inventory_overrides(
        enabled=test_override_enabled,
        overrides=test_inventory_overrides,
        text=test_override_text,
    )
    overrides_applied: list[dict[str, Any]] = []
    if overrides:
        inventory_map, overrides_applied = apply_test_inventory_overrides(inventory_map, overrides)
        logger.warning(
            "inventory delist TEST OVERRIDE applied count=%s codes=%s (feishu_called=%s)",
            len(overrides_applied),
            [item.get("code") for item in overrides_applied],
            feishu_called,
        )

    negative_codes: set[str] = set()
    for aid, items in per_account_items.items():
        for item in items:
            qty = _inventory_for_product_code(item.product_code, item.merchant_code, inventory_map)
            if qty is not None and qty < 0:
                negative_codes.add(item.product_code)

    per_account: list[AccountProductBreakdown] = []
    for aid in normalized_ids:
        items = per_account_items.get(aid, [])
        on_sale = per_account_sets.get(aid, set())
        exclusive = on_sale - common
        inv_by_code: dict[str, int] = {}
        account_negative: list[str] = []
        for item in items:
            qty = _inventory_for_product_code(item.product_code, item.merchant_code, inventory_map)
            if qty is not None:
                inv_by_code[item.product_code] = qty
                if qty < 0:
                    account_negative.append(item.product_code)
        per_account.append(
            AccountProductBreakdown(
                account_id=aid,
                on_sale_codes=_sorted_codes(on_sale),
                exclusive_codes=_sorted_codes(exclusive),
                negative_inventory_codes=sorted(account_negative, key=lambda c: c.casefold()),
                delist_candidate_codes=sorted(account_negative, key=lambda c: c.casefold()),
                inventory_by_code=inv_by_code,
                published_counts=count_snapshots.get(aid),
            )
        )

    diagnostics = {
        "on_sale_total": len(all_codes),
        "erp_codes_queried": len(erp_codes),
        "published_counts": {
            aid: {
                "total": snap.total_rows,
                "on_sale": snap.on_sale_rows,
                "delisted": snap.delisted_rows,
                "other": snap.other_status_rows,
            }
            for aid, snap in count_snapshots.items()
        },
    }
    if not all_codes:
        diagnostics["message"] = (
            "本地 published_products 未查到在售商品，已跳过飞书查询。"
            "请确认店铺是否选对、商品是否已写入「已发布商品」表且 status=on_sale。"
        )
    elif not feishu_called:
        diagnostics["message"] = "未发起飞书查询"
    elif feishu_error:
        diagnostics["message"] = f"飞书查询失败：{feishu_error}"
    elif feishu_rows_matched == 0:
        diagnostics["message"] = (
            f"已向飞书查询 {len(erp_codes)} 个编码，但未匹配到聚水潭 ERP 记录，请核对商品编码是否一致。"
        )
    else:
        diagnostics["message"] = (
            f"已查询飞书聚水潭 ERP：{len(erp_codes)} 个编码，命中 {feishu_rows_matched} 条。"
        )
    if overrides_applied:
        diagnostics["test_override_enabled"] = True
        diagnostics["test_overrides_applied"] = overrides_applied
        diagnostics["message"] += (
            f" 【测试覆盖】已人为改写 {len(overrides_applied)} 个编码可用数，用于联调下架链路。"
        )

    merged_inv_by_code: dict[str, int] = {}
    for aid, items in per_account_items.items():
        for item in items:
            qty = _inventory_for_product_code(item.product_code, item.merchant_code, inventory_map)
            if qty is not None:
                merged_inv_by_code[item.product_code] = qty

    return InventoryDelistAnalysis(
        account_ids=normalized_ids,
        common_on_sale_codes=_sorted_codes(common),
        all_on_sale_codes=_sorted_codes(all_codes),
        negative_inventory_codes=_sorted_codes(negative_codes),
        inventory_by_code=merged_inv_by_code,
        per_account=per_account,
        feishu_query_count=len(erp_codes),
        feishu_called=feishu_called,
        feishu_rows_matched=feishu_rows_matched,
        feishu_force_refresh=bool(force_feishu_refresh),
        feishu_error=feishu_error,
        database_available=db_ok,
        test_override_enabled=bool(overrides_applied),
        test_overrides_applied=overrides_applied,
        diagnostics=diagnostics,
    )

"""库存恢复上架 — 已下架记录 + 聚水潭可用数分析（多店联动）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import list_pending_relist_records
from pdd_agent.integrations.feishu.jushuitan_erp_inventory import load_jushuitan_inventory_map
from pdd_agent.inventory_delist.analysis import _inventory_for_product_code

logger = get_logger(__name__)


@dataclass(frozen=True)
class PendingRelistRecord:
    record_id: str
    account_id: str
    shop_display_name: str
    product_code: str
    merchant_code: str
    mapping_id: str
    pdd_product_id: str
    erp_available_qty: int | None
    is_common_on_sale: bool
    delisted_at: str


@dataclass
class RelistTarget:
    product_code: str
    account_ids: list[str] = field(default_factory=list)
    shop_names: list[str] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    available_qty: int | None = None
    is_multi_shop: bool = False
    was_common_delist: bool = False
    per_account: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class InventoryRelistAnalysis:
    account_ids: list[str]
    pending_record_count: int = 0
    unique_product_codes: list[str] = field(default_factory=list)
    common_pending_codes: list[str] = field(default_factory=list)
    relist_candidates: list[RelistTarget] = field(default_factory=list)
    still_negative_codes: list[RelistTarget] = field(default_factory=list)
    unknown_inventory_codes: list[RelistTarget] = field(default_factory=list)
    inventory_by_code: dict[str, int] = field(default_factory=dict)
    feishu_query_count: int = 0
    feishu_called: bool = False
    feishu_rows_matched: int = 0
    feishu_force_refresh: bool = False
    feishu_error: str = ""
    database_available: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _sorted_codes(codes: set[str]) -> list[str]:
    return sorted(codes, key=lambda c: c.casefold())


def _record_to_pending(row) -> PendingRelistRecord:
    delisted_at = row.delisted_at.isoformat(timespec="seconds") if row.delisted_at else ""
    shop = str(row.shop_display_name or "").strip()
    if not shop:
        shop = resolve_account_display_name(str(row.account_id or ""))
    return PendingRelistRecord(
        record_id=str(row.record_id or ""),
        account_id=str(row.account_id or ""),
        shop_display_name=shop,
        product_code=str(row.product_code or "").strip(),
        merchant_code=str(row.merchant_code or "").strip(),
        mapping_id=str(row.mapping_id or ""),
        pdd_product_id=str(row.pdd_product_id or ""),
        erp_available_qty=row.erp_available_qty,
        is_common_on_sale=bool(row.is_common_on_sale),
        delisted_at=delisted_at,
    )


def _build_target(
    product_code: str,
    records: list[PendingRelistRecord],
    *,
    available_qty: int | None,
    bucket: str,
) -> RelistTarget:
    account_ids = list(dict.fromkeys(r.account_id for r in records if r.account_id))
    shop_names = list(dict.fromkeys(r.shop_display_name for r in records if r.shop_display_name))
    record_ids = [r.record_id for r in records if r.record_id]
    was_common = any(r.is_common_on_sale for r in records) or len(account_ids) > 1
    per_account = [
        {
            "account_id": r.account_id,
            "shop_display_name": r.shop_display_name,
            "record_id": r.record_id,
            "mapping_id": r.mapping_id,
            "pdd_product_id": r.pdd_product_id,
            "delisted_at": r.delisted_at,
            "delist_erp_qty": r.erp_available_qty,
        }
        for r in records
    ]
    return RelistTarget(
        product_code=product_code,
        account_ids=account_ids,
        shop_names=shop_names,
        record_ids=record_ids,
        available_qty=available_qty,
        is_multi_shop=len(account_ids) > 1,
        was_common_delist=was_common,
        per_account=per_account,
    )


def analyze_inventory_relist_targets(
    account_ids: list[str],
    *,
    force_feishu_refresh: bool = False,
    min_available_qty: int = 0,
) -> InventoryRelistAnalysis:
    """
    读取所选店铺「已下架且未重新上架」记录，查聚水潭当前可用数。

    同一商品编码若在多家店铺均有待恢复记录，则必须多家一起上架（联动）。
    """
    from pdd_agent.db.session import is_database_available

    normalized_ids = list(dict.fromkeys(str(aid).strip() for aid in account_ids if str(aid).strip()))
    db_ok = is_database_available()

    if not normalized_ids:
        return InventoryRelistAnalysis(
            account_ids=[],
            database_available=db_ok,
            diagnostics={"message": "未选择任何店铺"},
        )

    if not db_ok:
        return InventoryRelistAnalysis(
            account_ids=normalized_ids,
            database_available=False,
            diagnostics={"message": "数据库不可用，无法读取下架记录"},
        )

    rows = list_pending_relist_records(account_ids=normalized_ids, limit=2000)
    pending = [_record_to_pending(row) for row in rows if row.product_code]

    grouped: dict[str, list[PendingRelistRecord]] = {}
    for item in pending:
        grouped.setdefault(item.product_code, []).append(item)

    unique_codes = _sorted_codes(set(grouped.keys()))
    common_codes = _sorted_codes(
        {code for code, items in grouped.items() if len({i.account_id for i in items}) > 1}
    )

    erp_lookup: set[str] = set()
    for code, items in grouped.items():
        erp_lookup.add(code)
        for item in items:
            if item.merchant_code:
                erp_lookup.add(item.merchant_code)

    inventory_map: dict[str, int] = {}
    feishu_called = False
    feishu_rows_matched = 0
    feishu_error = ""

    if erp_lookup:
        feishu_called = True
        try:
            inventory_map = load_jushuitan_inventory_map(
                codes=sorted(erp_lookup, key=lambda c: c.casefold()),
                force_refresh=bool(force_feishu_refresh),
            )
            feishu_rows_matched = len(inventory_map)
            logger.info(
                "inventory relist feishu query accounts=%s pending_records=%s codes=%s matched=%s",
                len(normalized_ids),
                len(pending),
                len(unique_codes),
                feishu_rows_matched,
            )
        except Exception as exc:
            feishu_error = str(exc)
            logger.exception("inventory relist feishu query failed")

    relist_candidates: list[RelistTarget] = []
    still_negative: list[RelistTarget] = []
    unknown_inventory: list[RelistTarget] = []
    merged_inv: dict[str, int] = {}

    for code in unique_codes:
        items = grouped.get(code, [])
        merchant = next((i.merchant_code for i in items if i.merchant_code), code)
        qty = _inventory_for_product_code(code, merchant, inventory_map)
        if qty is not None:
            merged_inv[code] = qty
        target = _build_target(code, items, available_qty=qty, bucket="")
        if qty is None:
            unknown_inventory.append(target)
        elif qty >= min_available_qty:
            relist_candidates.append(target)
        else:
            still_negative.append(target)

    diagnostics: dict[str, Any] = {
        "pending_records": len(pending),
        "unique_codes": len(unique_codes),
        "multi_shop_codes": len(common_codes),
        "relist_ready": len(relist_candidates),
        "still_negative": len(still_negative),
        "unknown_inventory": len(unknown_inventory),
    }

    if not pending:
        diagnostics["message"] = (
            "所选店铺暂无「已下架且未重新上架」的记录。"
            "请先完成负库存下架，或确认下架记录中「重新上架」仍为否。"
        )
    elif not feishu_called:
        diagnostics["message"] = "未发起飞书查询"
    elif feishu_error:
        diagnostics["message"] = f"飞书查询失败：{feishu_error}"
    elif feishu_rows_matched == 0:
        diagnostics["message"] = (
            f"已查询 {len(erp_lookup)} 个编码，但未匹配到聚水潭 ERP 记录。"
        )
    else:
        diagnostics["message"] = (
            f"待恢复 {len(unique_codes)} 个编码，"
            f"其中 {len(relist_candidates)} 个可用数已恢复（≥{min_available_qty}），"
            f"{len(common_codes)} 个为多店共同下架需联动上架。"
        )

    return InventoryRelistAnalysis(
        account_ids=normalized_ids,
        pending_record_count=len(pending),
        unique_product_codes=unique_codes,
        common_pending_codes=common_codes,
        relist_candidates=relist_candidates,
        still_negative_codes=still_negative,
        unknown_inventory_codes=unknown_inventory,
        inventory_by_code=merged_inv,
        feishu_query_count=len(erp_lookup),
        feishu_called=feishu_called,
        feishu_rows_matched=feishu_rows_matched,
        feishu_force_refresh=bool(force_feishu_refresh),
        feishu_error=feishu_error,
        database_available=db_ok,
        diagnostics=diagnostics,
    )

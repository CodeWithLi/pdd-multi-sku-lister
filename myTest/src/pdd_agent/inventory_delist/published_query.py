"""库存下架 — 在售已发布商品查询（独立封装，不修改 repositories）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from pdd_agent.db.models import PublishedProductORM
from pdd_agent.db.repositories import build_folder_selector
from pdd_agent.db.session import is_database_available, session_scope


@dataclass(frozen=True)
class OnSalePublishedItem:
    mapping_id: str
    account_id: str
    product_code: str
    family_code: str
    image_set: str
    merchant_code: str
    pdd_product_id: str
    selector: str
    status: str


@dataclass(frozen=True)
class PublishedCountSnapshot:
    account_id: str
    total_rows: int
    on_sale_rows: int
    delisted_rows: int
    other_status_rows: int


def count_published_by_account(account_id: str) -> PublishedCountSnapshot:
    account_id = str(account_id or "").strip()
    if not account_id or not is_database_available():
        return PublishedCountSnapshot(account_id, 0, 0, 0, 0)
    with session_scope() as session:
        rows = session.execute(
            select(PublishedProductORM.status, func.count())
            .where(PublishedProductORM.account_id == account_id)
            .group_by(PublishedProductORM.status)
        ).all()
    on_sale = delisted = other = 0
    for status, count in rows:
        text = str(status or "").strip().lower()
        qty = int(count or 0)
        if text == "on_sale":
            on_sale += qty
        elif text == "delisted":
            delisted += qty
        else:
            other += qty
    total = on_sale + delisted + other
    return PublishedCountSnapshot(account_id, total, on_sale, delisted, other)


def list_on_sale_codes(account_id: str) -> frozenset[str]:
    return frozenset(item.product_code for item in list_on_sale_items(account_id))


def list_on_sale_items(
    account_id: str,
    *,
    product_codes: set[str] | None = None,
    include_non_on_sale: bool = False,
) -> list[OnSalePublishedItem]:
    """
    读取已发布商品。

    默认仅 status=on_sale；include_non_on_sale=True 时包含非 delisted 记录（兼容历史脏数据）。
    """
    account_id = str(account_id or "").strip()
    if not account_id or not is_database_available():
        return []
    code_filter = {str(c).strip() for c in (product_codes or set()) if str(c).strip()}
    with session_scope() as session:
        query = select(PublishedProductORM).where(PublishedProductORM.account_id == account_id)
        if not include_non_on_sale:
            query = query.where(PublishedProductORM.status == "on_sale")
        else:
            query = query.where(PublishedProductORM.status != "delisted")
        rows = session.scalars(query).all()
    items: list[OnSalePublishedItem] = []
    for row in rows:
        product_code = str(row.product_code or "").strip()
        if not product_code:
            continue
        if code_filter and product_code not in code_filter:
            continue
        family_code = str(row.family_code or "").strip()
        image_set = str(row.image_set or "").strip()
        merchant_code = str(row.merchant_code or "").strip() or product_code
        selector = build_folder_selector(
            family_code=family_code,
            image_set=image_set,
            product_code=product_code,
        )
        items.append(
            OnSalePublishedItem(
                mapping_id=str(row.mapping_id or "").strip(),
                account_id=account_id,
                product_code=product_code,
                family_code=family_code,
                image_set=image_set,
                merchant_code=merchant_code,
                pdd_product_id=str(row.pdd_product_id or "").strip(),
                selector=selector,
                status=str(row.status or "").strip() or "on_sale",
            )
        )
    return items


def erp_lookup_codes_for_items(items: list[OnSalePublishedItem]) -> list[str]:
    """聚水潭查询用编码：商品编码 + 商家编码去重。"""
    codes: list[str] = []
    seen: set[str] = set()
    for item in items:
        for raw in (item.product_code, item.merchant_code):
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            codes.append(text)
    return codes

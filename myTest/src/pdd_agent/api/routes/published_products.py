"""Published products APIs."""

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.published_products import (
    PublishedProductDetailResponse,
    PublishedProductListResponse,
    PublishedProductOut,
)
from pdd_agent.api.services.catalog_service import get_product_detail
from pdd_agent.db.repositories import (
    get_published_product_by_mapping_id,
    search_published_products,
)
from pdd_agent.db.session import is_database_available
from pdd_agent.storage import TaskRunStore

router = APIRouter(prefix="/published-products", tags=["published-products"])


def _row_out(row) -> PublishedProductOut:
    return PublishedProductOut(
        mapping_id=row.mapping_id,
        account_id=row.account_id,
        source_run_id=row.source_run_id or "",
        product_code=row.product_code,
        image_set=row.image_set or "",
        listing_label=row.listing_label,
        merchant_code=row.merchant_code or "",
        pdd_product_id=row.pdd_product_id,
        status=row.status or "",
        published_at=row.published_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=PublishedProductListResponse)
def published_products_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    account_id: str = "",
    product_code: str = "",
    pdd_product_id: str = "",
):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL published products unavailable")
    rows, total = search_published_products(
        page=page,
        page_size=page_size,
        account_id=account_id.strip(),
        product_code=product_code.strip(),
        pdd_product_id=pdd_product_id.strip(),
    )
    return PublishedProductListResponse(
        items=[_row_out(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def _find_run_result_item(row) -> tuple[dict, dict]:
    if not row.source_run_id:
        return {}, {}
    record = TaskRunStore().load(row.source_run_id)
    if not record:
        return {}, {}
    source_run_result = dict(record.result or {})
    for item in source_run_result.get("results") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("product_code") or "") != row.product_code:
            continue
        if str(item.get("image_set") or "") != (row.image_set or ""):
            continue
        return item, source_run_result
    return {}, source_run_result


@router.get("/{mapping_id}", response_model=PublishedProductDetailResponse)
def published_product_detail(mapping_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL published products unavailable")
    row = get_published_product_by_mapping_id(mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"published product not found: {mapping_id}")
    run_result_item, source_run_result = _find_run_result_item(row)
    product_detail = get_product_detail(row.product_code)
    unit_detail = None
    if product_detail:
        for unit in product_detail.units:
            if unit.image_set == (row.image_set or ""):
                unit_detail = unit
                break
        if not unit_detail and product_detail.units:
            unit_detail = product_detail.units[0]
    return PublishedProductDetailResponse(
        published=_row_out(row),
        run_result_item=run_result_item,
        source_run_result=source_run_result,
        unit_detail=unit_detail,
    )

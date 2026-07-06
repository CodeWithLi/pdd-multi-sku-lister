"""上架商品属性配置 API。"""

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.listing_product_attributes import (
    ListingProductAttributeBatchUpdateIn,
    ListingProductAttributeListResponse,
    ListingProductAttributeOut,
    ListingProductAttributeUpdateIn,
)
from pdd_agent.db.repositories import (
    batch_update_listing_product_attributes,
    list_listing_product_attributes,
    seed_listing_product_attributes,
    update_listing_product_attribute,
)
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/listing-product-attributes", tags=["listing-product-attributes"])


def _row_out(row) -> ListingProductAttributeOut:
    return ListingProductAttributeOut(
        field_key=row.field_key,
        label=row.label,
        selected_value=row.selected_value or "",
        options=list(row.options or []),
        enabled=bool(row.enabled),
        sort_order=int(row.sort_order or 0),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _require_db():
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL listing product attributes unavailable")


@router.get("", response_model=ListingProductAttributeListResponse)
def listing_product_attributes_list(
    enabled_only: bool = Query(default=False, description="仅返回当前需要填写的属性"),
):
    _require_db()
    seed_listing_product_attributes()
    rows = list_listing_product_attributes(enabled_only=enabled_only)
    return ListingProductAttributeListResponse(items=[_row_out(row) for row in rows])


@router.put("/batch", response_model=ListingProductAttributeListResponse)
def listing_product_attributes_batch_update(body: ListingProductAttributeBatchUpdateIn):
    _require_db()
    if not body.attributes:
        raise HTTPException(status_code=422, detail="attributes is required")
    batch_update_listing_product_attributes(body.attributes)
    rows = list_listing_product_attributes(enabled_only=True)
    return ListingProductAttributeListResponse(items=[_row_out(row) for row in rows])


@router.put("/{field_key}", response_model=ListingProductAttributeOut)
def listing_product_attribute_update(field_key: str, body: ListingProductAttributeUpdateIn):
    _require_db()
    row = update_listing_product_attribute(
        field_key,
        selected_value=body.selected_value,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"listing product attribute not found or disabled: {field_key}",
        )
    return _row_out(row)

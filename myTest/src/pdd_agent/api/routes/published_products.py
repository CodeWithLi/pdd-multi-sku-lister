"""Published products APIs."""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from pdd_agent.api.schemas.published_products import (
    PublishedProductCreateResponse,
    PublishedProductDelistResponse,
    PublishedProductDeleteResponse,
    PublishedProductDetailResponse,
    PublishedProductListResponse,
    PublishedProductLookupResponse,
    PublishedProductManualCreateIn,
    PublishedProductOut,
)
from pdd_agent.api.schemas.catalog import ListingUnitOut, SkuComboOut
from pdd_agent.api.services.catalog_service import get_product_detail
from pdd_agent.api.services.published_price_status import derive_price_sync_status
from pdd_agent.api.services.published_product_service import create_manual_published_product
from pdd_agent.api.services.task_queue import enqueue_delist_task
from pdd_agent.api.services.task_runner import (
    create_delist_run,
    create_published_goods_lookup_run,
    execute_published_goods_lookup,
)
from pdd_agent.db.repositories import (
    delete_published_product,
    get_published_product_by_mapping_id,
    search_published_products,
)
from pdd_agent.db.session import is_database_available
from pdd_agent.domain.enums import RunStatus
from pdd_agent.storage import TaskRunStore

router = APIRouter(prefix="/published-products", tags=["published-products"])


def _row_out(row) -> PublishedProductOut:
    price_sync_status, price_sync_at = derive_price_sync_status(row.spec_metadata or {})
    return PublishedProductOut(
        mapping_id=row.mapping_id,
        account_id=row.account_id,
        source_run_id=row.source_run_id or "",
        product_code=row.product_code,
        family_code=row.family_code or "",
        image_set=row.image_set or "",
        listing_label=row.listing_label,
        merchant_code=row.merchant_code or "",
        pdd_product_id=row.pdd_product_id,
        status=row.status or "",
        published_at=row.published_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        spec_metadata=row.spec_metadata or {},
        price_sync_status=price_sync_status,
        price_sync_at=price_sync_at,
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


@router.post("/manual", response_model=PublishedProductCreateResponse)
def create_manual_published(body: PublishedProductManualCreateIn):
    """手动添加拼多多已有商品（非本工具上架）到 published_products 映射表。"""
    result = create_manual_published_product(
        account_id=body.account_id,
        pdd_product_id=body.pdd_product_id,
        product_code=body.product_code,
        listing_label=body.listing_label,
        family_code=body.family_code,
        image_set=body.image_set,
        merchant_code=body.merchant_code,
        status=body.status,
        note=body.note,
        import_catalog_skus=body.import_catalog_skus,
    )
    row = result["published"]
    hints = result.get("catalog_hints") or []
    message = "已手动添加商品映射"
    if hints:
        message = f"{message}；{'；'.join(hints)}"
    return PublishedProductCreateResponse(
        published=_row_out(row),
        catalog_hints=hints,
        message=message,
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


def _unit_detail_from_spec_metadata(row) -> ListingUnitOut | None:
    meta = row.spec_metadata or {}
    if not isinstance(meta, dict):
        return None
    skus = meta.get("skus")
    if not isinstance(skus, list):
        return None
    carousel_images = [str(item) for item in (meta.get("carousel_images") or [])]
    detail_images = [str(item) for item in (meta.get("detail_images") or [])]
    return ListingUnitOut(
        product_code=str(meta.get("product_code") or row.product_code or ""),
        family_code=str(meta.get("family_code") or row.family_code or ""),
        image_set=str(meta.get("image_set") or row.image_set or ""),
        listing_label=str(meta.get("listing_label") or row.listing_label or ""),
        merchant_code=str(meta.get("merchant_code") or row.merchant_code or ""),
        root=str(meta.get("root") or ""),
        carousel_images=carousel_images,
        detail_images=detail_images,
        carousel_count=len(carousel_images),
        detail_count=len(detail_images),
        sku_count=len(skus),
        style_codes=list(meta.get("style_codes") or []),
        model_codes=list(meta.get("model_codes") or []),
        warnings=[],
        skus=[
            SkuComboOut(
                style_code=str(sku.get("style_code") or ""),
                style_name=str(sku.get("style_name") or ""),
                model_code=str(sku.get("model_code") or ""),
                model_name=str(sku.get("model_name") or ""),
                combo_folder=str(sku.get("combo_folder") or ""),
                preview_image=str(sku.get("preview_image") or ""),
                inventory=str(sku.get("inventory") or ""),
                group_price=str(sku.get("group_price") or ""),
                single_price=str(sku.get("single_price") or ""),
            )
            for sku in skus
            if isinstance(sku, dict)
        ],
    )


@router.get("/{mapping_id}", response_model=PublishedProductDetailResponse)
def published_product_detail(mapping_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL published products unavailable")
    row = get_published_product_by_mapping_id(mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"published product not found: {mapping_id}")
    run_result_item, source_run_result = _find_run_result_item(row)
    unit_detail = _unit_detail_from_spec_metadata(row)
    if not unit_detail:
        product_detail = get_product_detail(row.product_code)
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


@router.post("/{mapping_id}/delist", response_model=PublishedProductDelistResponse)
def delist_published_product(mapping_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL published products unavailable")
    row = get_published_product_by_mapping_id(mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"published product not found: {mapping_id}")
    if not row.pdd_product_id:
        raise HTTPException(status_code=422, detail="published product has no pdd_product_id")
    if (row.status or "") == "delisted":
        raise HTTPException(status_code=409, detail="published product already marked delisted")

    run_id = create_delist_run(row.account_id)
    TaskRunStore().update_status(run_id, RunStatus.PENDING, "queued precise published-product delist")
    enqueue_delist_task(
        run_id=run_id,
        account_id=row.account_id,
        dry_run=False,
        delist_params={
            "target_mapping_id": row.mapping_id,
            "target_product_id": row.pdd_product_id,
            "dry_run": False,
            "mode": "published_product_exact",
        },
        scheduled_at=datetime.now(),
    )
    return PublishedProductDelistResponse(
        run_id=run_id,
        status=RunStatus.PENDING.value,
        message=f"precise delist queued for product_id={row.pdd_product_id}",
    )


@router.post("/{mapping_id}/lookup-pdd-goods", response_model=PublishedProductLookupResponse)
async def lookup_pdd_goods(mapping_id: str, background: BackgroundTasks):
    """在拼多多商品列表按商品 ID 反查，并打开商品编辑页（第一阶段）。"""
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL published products unavailable")
    row = get_published_product_by_mapping_id(mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"published product not found: {mapping_id}")
    if not row.pdd_product_id:
        raise HTTPException(status_code=422, detail="published product has no pdd_product_id")

    run_id = create_published_goods_lookup_run(row.account_id)
    TaskRunStore().update_status(run_id, RunStatus.PENDING, "queued published goods lookup")
    background.add_task(
        execute_published_goods_lookup,
        run_id=run_id,
        account_id=row.account_id,
        mapping_id=mapping_id,
    )
    return PublishedProductLookupResponse(
        run_id=run_id,
        status=RunStatus.PENDING.value,
        message=f"goods lookup queued for product_id={row.pdd_product_id}",
    )


@router.delete("/{mapping_id}", response_model=PublishedProductDeleteResponse)
def remove_published_product(mapping_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL published products unavailable")
    row = get_published_product_by_mapping_id(mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"published product not found: {mapping_id}")
    if not delete_published_product(mapping_id):
        raise HTTPException(status_code=500, detail=f"failed to delete published product: {mapping_id}")
    return PublishedProductDeleteResponse(
        mapping_id=mapping_id,
        message="deleted from published_products table only; PDD listing unchanged",
    )

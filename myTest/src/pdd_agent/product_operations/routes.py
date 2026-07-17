"""商品操作 HTTP 路由。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from pdd_agent.product_operations.schemas import (
    DelistAllStoresIn,
    DelistAllStoresOut,
    PricePreviewIn,
    PriceUpdateIn,
    PublishedProductOptionListOut,
    PublishedProductOptionOut,
    ProductOperationRunOut,
    StoreDelistRunOut,
)
from pdd_agent.product_operations.service import (
    create_price_operation_run,
    enqueue_product_code_delist_all_stores,
    execute_price_preview,
    execute_price_update,
    list_published_product_options,
)

router = APIRouter(prefix="/product-operations", tags=["product-operations"])


@router.get("/published-products", response_model=PublishedProductOptionListOut)
def get_published_product_options(account_id: str = ""):
    items = list_published_product_options(account_id=account_id)
    return PublishedProductOptionListOut(
        total=len(items),
        items=[PublishedProductOptionOut(**item) for item in items],
    )


@router.post("/delist-all-stores", response_model=DelistAllStoresOut)
def delist_product_all_stores(body: DelistAllStoresIn):
    try:
        rows = enqueue_product_code_delist_all_stores(body.product_code, dry_run=body.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DelistAllStoresOut(
        product_code=body.product_code,
        dry_run=body.dry_run,
        total=len(rows),
        runs=[StoreDelistRunOut(**row) for row in rows],
        message=f"已向 {len(rows)} 家店铺提交商品编码扫描下架任务",
    )


@router.post("/price-preview", response_model=ProductOperationRunOut)
async def preview_product_prices(body: PricePreviewIn, background: BackgroundTasks):
    run_id = create_price_operation_run(body.account_id, f"queued price preview: {body.product_code}")
    background.add_task(
        execute_price_preview,
        run_id=run_id,
        account_id=body.account_id,
        product_code=body.product_code,
    )
    return ProductOperationRunOut(run_id=run_id, message="规格读取任务已提交")


@router.post("/price-update", response_model=ProductOperationRunOut)
async def update_product_prices(body: PriceUpdateIn, background: BackgroundTasks):
    run_id = create_price_operation_run(body.account_id, f"queued price update: {body.product_code}")
    background.add_task(
        execute_price_update,
        run_id=run_id,
        account_id=body.account_id,
        product_code=body.product_code,
        expected_product_id=body.pdd_product_id,
        updates=[
            {"spec_code": item.spec_code, "group_price": str(item.group_price)}
            for item in body.updates
        ],
    )
    return ProductOperationRunOut(run_id=run_id, message="拼单价修改任务已提交")

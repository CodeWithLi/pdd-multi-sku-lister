"""库存下架 — HTTP 路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pdd_agent.inventory_delist.config import InventoryDelistScheduleConfig
from pdd_agent.inventory_delist.schemas import (
    InventoryDelistJobListOut,
    InventoryDelistJobOut,
    InventoryDelistPreviewIn,
    InventoryDelistPreviewOut,
    InventoryDelistRecordListOut,
    InventoryDelistRecordOut,
    InventoryRelistPreviewIn,
    InventoryRelistPreviewOut,
    InventoryDelistScheduleOut,
    InventoryDelistScheduleUpdateIn,
    InventoryDelistTriggerIn,
    InventoryDelistTriggerOut,
    OnSaleCodesIn,
    OnSaleCodesOut,
)
from pdd_agent.inventory_delist.service import (
    get_inventory_delist_job,
    get_schedule_status,
    list_inventory_delist_jobs,
    list_inventory_delist_record_items,
    list_on_sale_product_codes,
    preview_inventory_delist,
    preview_inventory_relist,
    trigger_inventory_delist_run,
    update_schedule,
)

router = APIRouter(prefix="/inventory-delist", tags=["inventory-delist"])


@router.get("/schedule", response_model=InventoryDelistScheduleOut)
def get_inventory_delist_schedule():
    return InventoryDelistScheduleOut(**get_schedule_status())


@router.put("/schedule", response_model=InventoryDelistScheduleOut)
def put_inventory_delist_schedule(body: InventoryDelistScheduleUpdateIn):
    cfg = InventoryDelistScheduleConfig(
        enabled=body.enabled,
        interval_hours=body.interval_hours,
        account_ids=list(body.account_ids),
        execution_mode=body.execution_mode,
        delist_spec_code_search_enabled=body.delist_spec_code_search_enabled,
    )
    return InventoryDelistScheduleOut(**update_schedule(cfg))


@router.post("/on-sale-codes", response_model=OnSaleCodesOut)
def post_on_sale_codes(body: OnSaleCodesIn):
    try:
        data = list_on_sale_product_codes(account_ids=body.account_ids)
        return OnSaleCodesOut(**data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/preview", response_model=InventoryDelistPreviewOut)
def post_inventory_delist_preview(body: InventoryDelistPreviewIn):
    try:
        data = preview_inventory_delist(
            account_ids=body.account_ids,
            force_feishu_refresh=body.force_feishu_refresh,
            test_override_enabled=body.test_override_enabled,
            test_inventory_overrides=body.test_inventory_overrides or None,
            test_override_text=body.test_override_text or None,
        )
        return InventoryDelistPreviewOut(**data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/relist/preview", response_model=InventoryRelistPreviewOut)
def post_inventory_relist_preview(body: InventoryRelistPreviewIn):
    try:
        data = preview_inventory_relist(
            account_ids=body.account_ids,
            force_feishu_refresh=body.force_feishu_refresh,
            min_available_qty=body.min_available_qty,
        )
        return InventoryRelistPreviewOut(**data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/trigger", response_model=InventoryDelistTriggerOut)
def post_inventory_delist_trigger(body: InventoryDelistTriggerIn):
    try:
        job = trigger_inventory_delist_run(
            account_ids=body.account_ids,
            execution_mode=body.execution_mode,
            delist_spec_code_search_enabled=body.delist_spec_code_search_enabled,
            trigger="manual",
            test_override_enabled=body.test_override_enabled,
            test_inventory_overrides=body.test_inventory_overrides or None,
            test_override_text=body.test_override_text or None,
            delist_dry_run=body.delist_dry_run,
        )
        return InventoryDelistTriggerOut(job=InventoryDelistJobOut(**job))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/jobs", response_model=InventoryDelistJobListOut)
def get_inventory_delist_jobs(limit: int = 20):
    items = list_inventory_delist_jobs(limit=max(1, min(50, limit)))
    return InventoryDelistJobListOut(
        total=len(items),
        items=[InventoryDelistJobOut(**item) for item in items],
    )


@router.get("/records", response_model=InventoryDelistRecordListOut)
def get_inventory_delist_records(
    account_id: str | None = None,
    job_id: str | None = None,
    limit: int = 50,
):
    items = list_inventory_delist_record_items(
        account_id=account_id,
        job_id=job_id,
        limit=max(1, min(200, limit)),
    )
    return InventoryDelistRecordListOut(
        total=len(items),
        items=[InventoryDelistRecordOut(**item) for item in items],
    )


@router.get("/jobs/{job_id}", response_model=InventoryDelistJobOut)
def get_inventory_delist_job_detail(job_id: str):
    job = get_inventory_delist_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return InventoryDelistJobOut(**job)

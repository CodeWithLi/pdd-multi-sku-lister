"""整合链路 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.pipelines import (
    AutoUploadConfigResponse,
    AutoUploadConfigUpdateIn,
    IntegratedPipelineBatchResponse,
    IntegratedPipelineBatchStartRequest,
    IntegratedPipelineListResponse,
    IntegratedPipelineResponse,
    IntegratedPipelineStartRequest,
    PipelineExcelFallbackOut,
    PipelineExcelFallbackUpdateIn,
)
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.api.services.pipeline_service import (
    cancel_integrated_pipeline,
    get_pipeline,
    list_pipelines,
    start_integrated_pipeline,
    start_integrated_pipeline_batch,
)
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.session import is_database_available
from pdd_agent.api.schemas.feishu_inspect import FeishuInspectListingPricesOut
from pdd_agent.integrations.feishu.config import excel_fallback_enabled, save_pipeline_excel_fallback_to_config
from pdd_agent.integrations.feishu.listing_feishu_inspect_store import (
    capture_and_save_pipeline_feishu_inspect,
    load_pipeline_feishu_inspect,
    merchant_codes_for_pipeline,
)
from pdd_agent.integrations.minio.auto_pipeline import (
    AutoPipelineConfig,
    load_auto_pipeline_config,
    save_auto_pipeline_config,
)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _dedupe_account_ids(account_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(a.strip() for a in account_ids if a and a.strip()))


def _normalize_batch_items(body: IntegratedPipelineBatchStartRequest) -> list[dict]:
    if body.items:
        return [
            {
                "account_id": item.account_id.strip(),
                "product_codes": list(dict.fromkeys(c.strip() for c in item.product_codes if c.strip())),
            }
            for item in body.items
        ]
    account_ids = _dedupe_account_ids(body.account_ids)
    product_codes = list(dict.fromkeys(c.strip() for c in body.product_codes if c.strip()))
    return [{"account_id": account_id, "product_codes": product_codes} for account_id in account_ids]


def _clear_excel_data_caches() -> None:
    from pdd_agent.integrations.feishu.cache import clear_feishu_data_caches

    clear_feishu_data_caches()


@router.get("/integrated/excel-fallback", response_model=PipelineExcelFallbackOut)
def get_integrated_excel_fallback():
    """读取整合链路「飞书无数据时回退本地 Excel」开关。"""
    return PipelineExcelFallbackOut(enabled=excel_fallback_enabled())


@router.put("/integrated/excel-fallback", response_model=PipelineExcelFallbackOut)
def update_integrated_excel_fallback(body: PipelineExcelFallbackUpdateIn):
    """保存整合链路 Excel 回退开关（写入 feishu.yaml）。"""
    save_pipeline_excel_fallback_to_config(body.enabled)
    _clear_excel_data_caches()
    return PipelineExcelFallbackOut(enabled=bool(body.enabled))


def _auto_upload_config_response() -> AutoUploadConfigResponse:
    cfg = load_auto_pipeline_config()
    return AutoUploadConfigResponse(**cfg.model_dump())


@router.get("/auto-upload-config", response_model=AutoUploadConfigResponse)
def get_auto_upload_config():
    """读取 RabbitMQ 自动上架配置（写入 minio.yaml auto_pipeline）。"""
    return _auto_upload_config_response()


@router.put("/auto-upload-config", response_model=AutoUploadConfigResponse)
def update_auto_upload_config(body: AutoUploadConfigUpdateIn):
    """保存 RabbitMQ 自动上架配置。"""
    if body.enabled:
        account_id = str(body.account_id or "").strip()
        if not account_id:
            raise HTTPException(status_code=400, detail="开启自动上架时请选择店铺")
        if not get_account_or_none(account_id):
            raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")
    try:
        saved = save_auto_pipeline_config(AutoPipelineConfig.model_validate(body.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AutoUploadConfigResponse(**saved.model_dump())


@router.post("/integrated", response_model=IntegratedPipelineResponse)
def start_integrated(body: IntegratedPipelineStartRequest):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用，无法创建整合链路")
    if not get_account_or_none(body.account_id):
        raise HTTPException(status_code=404, detail=f"unknown account: {body.account_id}")
    try:
        data = start_integrated_pipeline(
            account_id=body.account_id,
            product_codes=body.product_codes,
            activity_id=body.activity_id,
            activity_ids=body.activity_ids,
            category_keyword=body.category_keyword,
            auto_promotion=body.auto_promotion,
            auto_limited_time_setup=body.auto_limited_time_setup,
            continue_after_limited_time_failure=body.continue_after_limited_time_failure,
            continue_after_activity_failure=body.continue_after_activity_failure,
            activity_delay_hours=body.activity_delay_hours,
            demo_mode=body.demo_mode,
            platform_listing_code=body.platform_listing_code,
            slot_alignment_test=body.slot_alignment_test,
            skip_listing=body.skip_listing,
            listing_skip_selectors=body.listing_skip_selectors,
            material_source=body.material_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IntegratedPipelineResponse(**data)


@router.post("/integrated/batch", response_model=IntegratedPipelineBatchResponse)
def start_integrated_batch(body: IntegratedPipelineBatchStartRequest):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用，无法创建整合链路")
    settings = load_yaml_settings()
    try:
        items = _normalize_batch_items(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not items:
        raise HTTPException(status_code=422, detail="items cannot be empty")

    for item in items:
        account_id = str(item.get("account_id") or "").strip()
        if not account_id:
            raise HTTPException(status_code=422, detail="account_id is required for each item")
        if not get_account_or_none(account_id, settings):
            raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")
        if not item.get("product_codes"):
            raise HTTPException(status_code=422, detail=f"product_codes is required for account: {account_id}")

    try:
        data = start_integrated_pipeline_batch(
            items=items,
            activity_id=body.activity_id,
            activity_ids=body.activity_ids,
            category_keyword=body.category_keyword,
            auto_promotion=body.auto_promotion,
            auto_limited_time_setup=body.auto_limited_time_setup,
            continue_after_limited_time_failure=body.continue_after_limited_time_failure,
            continue_after_activity_failure=body.continue_after_activity_failure,
            activity_delay_hours=body.activity_delay_hours,
            demo_mode=body.demo_mode,
            platform_listing_code=body.platform_listing_code,
            slot_alignment_test=body.slot_alignment_test,
            skip_listing=body.skip_listing,
            listing_skip_selectors=body.listing_skip_selectors,
            store_start_delay_min_seconds=body.store_start_delay_min_seconds,
            store_start_delay_max_seconds=body.store_start_delay_max_seconds,
            max_concurrent_stores=body.max_concurrent_stores,
            material_source=body.material_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IntegratedPipelineBatchResponse(**data)


@router.get("/integrated", response_model=IntegratedPipelineListResponse)
def list_integrated(
    page: int = 1,
    page_size: int = 10,
    batch_id: str = "",
):
    if not is_database_available():
        return IntegratedPipelineListResponse(items=[], total=0, page=1, page_size=page_size)
    data = list_pipelines(page=page, page_size=page_size, batch_id=batch_id)
    return IntegratedPipelineListResponse(
        items=[IntegratedPipelineResponse(**item) for item in data.get("items") or []],
        total=int(data.get("total") or 0),
        page=int(data.get("page") or 1),
        page_size=int(data.get("page_size") or page_size),
    )


@router.get("/integrated/{pipeline_id}/feishu-inspect", response_model=FeishuInspectListingPricesOut)
def get_integrated_feishu_inspect(pipeline_id: str, refresh: bool = False):
    """读取整合链路已保存的飞书定价数据；refresh=true 时重新拉取并覆盖。"""
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    data = get_pipeline(pipeline_id)
    if not data:
        raise HTTPException(status_code=404, detail="pipeline not found")

    if refresh:
        codes = merchant_codes_for_pipeline(data) or list(data.get("product_codes") or [])
        if not codes:
            raise HTTPException(status_code=422, detail="该链路没有可查询的商品编码")
        result = capture_and_save_pipeline_feishu_inspect(pipeline_id, codes, force_refresh=True)
        return FeishuInspectListingPricesOut(**result, from_cache=False)

    cached = load_pipeline_feishu_inspect(pipeline_id)
    if not cached:
        raise HTTPException(status_code=404, detail="该链路尚未记录飞书定价数据")
    return FeishuInspectListingPricesOut(**cached, from_cache=True)


@router.get("/integrated/{pipeline_id}", response_model=IntegratedPipelineResponse)
def get_integrated(pipeline_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    data = get_pipeline(pipeline_id)
    if not data:
        raise HTTPException(status_code=404, detail="pipeline not found")
    return IntegratedPipelineResponse(**data)


@router.post("/integrated/{pipeline_id}/cancel", response_model=IntegratedPipelineResponse)
def cancel_integrated(pipeline_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    try:
        data = cancel_integrated_pipeline(pipeline_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "pipeline not found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return IntegratedPipelineResponse(**data)

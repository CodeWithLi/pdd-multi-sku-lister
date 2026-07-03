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
    PipelineLogSpecSkuRowsOut,
    PipelineLogSpecSkuRowsUpdateIn,
    PipelinePlatformSkipDedupeOut,
    PipelinePlatformSkipDedupeUpdateIn,
    PipelineAccessoryCostPricingOut,
    PipelineAccessoryCostPricingUpdateIn,
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
from pdd_agent.integrations.feishu.config import (
    accessory_cost_pricing_enabled,
    excel_fallback_enabled,
    platform_skip_dedupe_enabled,
    load_feishu_config,
    save_pipeline_accessory_cost_pricing_to_config,
    save_pipeline_excel_fallback_to_config,
    save_pipeline_platform_skip_dedupe_to_config,
    save_pdd_upload_log_spec_rows_to_config,
)
from pdd_agent.integrations.feishu.platform_skip_dedupe_cache import get_platform_skip_dedupe_status
from pdd_agent.api.services.platform_skip_dedupe_scheduler import get_platform_skip_dedupe_scheduler
from pdd_agent.integrations.feishu.pdd_upload_spec_log import log_spec_sku_rows_enabled
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


@router.get("/integrated/accessory-cost-pricing", response_model=PipelineAccessoryCostPricingOut)
def get_integrated_accessory_cost_pricing():
    """读取整合链路「配件成本定价」开关。"""
    cfg = load_feishu_config()
    pipe = cfg.pipeline
    return PipelineAccessoryCostPricingOut(
        enabled=accessory_cost_pricing_enabled(cfg),
        float_min=float(pipe.accessory_cost_float_min),
        float_max=float(pipe.accessory_cost_float_max),
    )


@router.put("/integrated/accessory-cost-pricing", response_model=PipelineAccessoryCostPricingOut)
def update_integrated_accessory_cost_pricing(body: PipelineAccessoryCostPricingUpdateIn):
    """保存整合链路「配件成本定价」开关（写入 feishu.yaml）。"""
    save_pipeline_accessory_cost_pricing_to_config(body.enabled)
    cfg = load_feishu_config()
    pipe = cfg.pipeline
    return PipelineAccessoryCostPricingOut(
        enabled=bool(body.enabled),
        float_min=float(pipe.accessory_cost_float_min),
        float_max=float(pipe.accessory_cost_float_max),
    )


@router.get("/integrated/log-spec-sku-rows", response_model=PipelineLogSpecSkuRowsOut)
def get_integrated_log_spec_sku_rows():
    """读取「上架成功按规格编码展开写发布日志」开关。"""
    return PipelineLogSpecSkuRowsOut(enabled=log_spec_sku_rows_enabled())


@router.put("/integrated/log-spec-sku-rows", response_model=PipelineLogSpecSkuRowsOut)
def update_integrated_log_spec_sku_rows(body: PipelineLogSpecSkuRowsUpdateIn):
    """保存按规格展开写发布日志开关（写入 feishu.yaml pdd_upload_log）。"""
    save_pdd_upload_log_spec_rows_to_config(body.enabled)
    return PipelineLogSpecSkuRowsOut(enabled=bool(body.enabled))


def _platform_skip_dedupe_response() -> PipelinePlatformSkipDedupeOut:
    status = get_platform_skip_dedupe_status()
    scheduler = get_platform_skip_dedupe_scheduler()
    return PipelinePlatformSkipDedupeOut(
        enabled=bool(status.get("enabled")),
        sync_seconds=int(status.get("sync_seconds") or 300),
        code_count=int(status.get("code_count") or 0),
        updated_at=str(status.get("updated_at") or ""),
        redis_available=bool(status.get("redis_available")),
        last_sync_at=str(scheduler.last_sync_at or status.get("updated_at") or ""),
        last_error=str(scheduler.last_error or ""),
    )


@router.get("/integrated/platform-skip-dedupe", response_model=PipelinePlatformSkipDedupeOut)
def get_integrated_platform_skip_dedupe():
    """读取「平台跳过去重」开关及 Redis 缓存状态。"""
    return _platform_skip_dedupe_response()


@router.put("/integrated/platform-skip-dedupe", response_model=PipelinePlatformSkipDedupeOut)
async def update_integrated_platform_skip_dedupe(body: PipelinePlatformSkipDedupeUpdateIn):
    """保存「平台跳过去重」开关；开启时立即同步飞书跳过编码到 Redis。"""
    save_pipeline_platform_skip_dedupe_to_config(body.enabled)
    scheduler = get_platform_skip_dedupe_scheduler()
    if body.enabled:
        if not scheduler.is_running:
            scheduler.start()
        await scheduler.sync_once()
    return _platform_skip_dedupe_response()


@router.post("/integrated/platform-skip-dedupe/sync", response_model=PipelinePlatformSkipDedupeOut)
async def sync_integrated_platform_skip_dedupe():
    """手动触发一次飞书跳过编码同步（需已开启开关）。"""
    if not platform_skip_dedupe_enabled():
        raise HTTPException(status_code=400, detail="platform_skip_dedupe is disabled")
    scheduler = get_platform_skip_dedupe_scheduler()
    result = await scheduler.sync_once()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=str(result.get("error") or "sync failed"))
    return _platform_skip_dedupe_response()


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
            promote_after_limited_time_failure=body.promote_after_limited_time_failure,
            activity_delay_hours=body.activity_delay_hours,
            demo_mode=body.demo_mode,
            platform_listing_code=body.platform_listing_code,
            slot_alignment_test=body.slot_alignment_test,
            spec_fill_verify_test=body.spec_fill_verify_test,
            category_next_burst_demo=body.category_next_burst_demo,
            skip_listing=body.skip_listing,
            listing_skip_selectors=body.listing_skip_selectors,
            material_source=body.material_source,
            relist_strategy=body.relist_strategy,
            listing_throttle_enabled=body.listing_throttle_enabled,
            listing_batch_set_count=body.listing_batch_set_count,
            listing_batch_interval_minutes=body.listing_batch_interval_minutes,
            listing_per_batch_limited_time_enabled=body.listing_per_batch_limited_time_enabled,
            listing_per_batch_campaign_enabled=body.listing_per_batch_campaign_enabled,
            delist_spec_code_search_enabled=body.delist_spec_code_search_enabled,
            activity_limited_time_success_only=body.activity_limited_time_success_only,
            trigger_source="manual",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if data.get("commerce_queued"):
        return IntegratedPipelineResponse(
            commerce_queued=True,
            intent_id=str(data.get("intent_id") or ""),
            account_id=str(data.get("account_id") or body.account_id),
            product_codes=list(data.get("product_codes") or body.product_codes),
            block_reason=str(data.get("block_reason") or ""),
            block_reason_label=str(data.get("block_reason_label") or ""),
            wake_at=str(data.get("wake_at") or ""),
            status="queued",
            current_step="commerce_queued",
        )
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
            promote_after_limited_time_failure=body.promote_after_limited_time_failure,
            activity_delay_hours=body.activity_delay_hours,
            demo_mode=body.demo_mode,
            platform_listing_code=body.platform_listing_code,
            slot_alignment_test=body.slot_alignment_test,
            spec_fill_verify_test=body.spec_fill_verify_test,
            category_next_burst_demo=body.category_next_burst_demo,
            skip_listing=body.skip_listing,
            listing_skip_selectors=body.listing_skip_selectors,
            store_start_delay_min_seconds=body.store_start_delay_min_seconds,
            store_start_delay_max_seconds=body.store_start_delay_max_seconds,
            max_concurrent_stores=body.max_concurrent_stores,
            material_source=body.material_source,
            relist_strategy=body.relist_strategy,
            listing_throttle_enabled=body.listing_throttle_enabled,
            listing_batch_set_count=body.listing_batch_set_count,
            listing_batch_interval_minutes=body.listing_batch_interval_minutes,
            listing_per_batch_limited_time_enabled=body.listing_per_batch_limited_time_enabled,
            listing_per_batch_campaign_enabled=body.listing_per_batch_campaign_enabled,
            store_sequential_enabled=body.store_sequential_enabled,
            delist_spec_code_search_enabled=body.delist_spec_code_search_enabled,
            activity_limited_time_success_only=body.activity_limited_time_success_only,
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

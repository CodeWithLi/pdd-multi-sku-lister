"""整合链路 API。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.pipelines import (
    AutoUploadConfigResponse,
    AutoUploadConfigUpdateIn,
    IntegratedPipelineBatchResponse,
    IntegratedPipelineBatchStartRequest,
    IntegratedPipelineBatchProductStageListResponse,
    IntegratedPipelineBatchProductStagePatchRequest,
    IntegratedPipelineBatchProductStagePatchResponse,
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
    PipelineAccessoryTieredFloatOut,
    PipelineAccessoryTieredFloatUpdateIn,
    PipelineSubmitAiTitleOut,
    PipelineSubmitAiTitleTestIn,
    PipelineSubmitAiTitleTestOut,
    PipelineSubmitAiTitleUpdateIn,
    PerBatchLtChunkSettingsOut,
    PerBatchLtChunkSettingsUpdateIn,
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
from pdd_agent.db.repositories import get_integrated_pipeline
from pdd_agent.api.schemas.pipeline_batch_limited_time_retry import (
    PipelineBatchLimitedTimeRetryAllStartResponse,
    PipelineBatchLimitedTimeRetryEligibilityOut,
    PipelineBatchLimitedTimeRetryStartRequest,
    PipelineBatchLimitedTimeRetryStartResponse,
)
from pdd_agent.api.schemas.pipeline_late_retry import (
    PipelineLateRetryStartRequest,
    PipelineLateRetryStartResponse,
)
from pdd_agent.api.schemas.feishu_inspect import FeishuInspectListingPricesOut
from pdd_agent.integrations.feishu.config import (
    accessory_cost_pricing_enabled,
    accessory_cost_tiered_float_enabled,
    excel_fallback_enabled,
    platform_skip_dedupe_enabled,
    load_feishu_config,
    save_pipeline_accessory_cost_pricing_to_config,
    save_pipeline_accessory_tiered_float_to_config,
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
from pdd_agent.api.services.submit_ai_title_config_service import (
    get_submit_ai_title_config,
    update_submit_ai_title_config,
)
from pdd_agent.api.services.catalog_service import MaterialSource
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.skills.listing.catalog import resolve_submit_ai_title_test_assets
from pdd_agent.skills.listing.listing_submit_ai_title import generate_submit_ai_title

router = APIRouter(prefix="/pipelines", tags=["pipelines"])
logger = logging.getLogger(__name__)


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


@router.get("/integrated/accessory-tiered-float", response_model=PipelineAccessoryTieredFloatOut)
def get_integrated_accessory_tiered_float():
    """读取「子商品档位浮动」开关。"""
    return PipelineAccessoryTieredFloatOut(enabled=accessory_cost_tiered_float_enabled())


@router.put("/integrated/accessory-tiered-float", response_model=PipelineAccessoryTieredFloatOut)
def update_integrated_accessory_tiered_float(body: PipelineAccessoryTieredFloatUpdateIn):
    """保存「子商品档位浮动」开关（写入 feishu.yaml）。"""
    save_pipeline_accessory_tiered_float_to_config(body.enabled)
    return PipelineAccessoryTieredFloatOut(enabled=bool(body.enabled))


@router.get("/integrated/submit-ai-title", response_model=PipelineSubmitAiTitleOut)
def get_integrated_submit_ai_title():
    """读取「提交前 AI 改标题」配置（独立于历史 page_ai 标题流程）。"""
    cfg = get_submit_ai_title_config()
    return PipelineSubmitAiTitleOut(
        enabled=cfg.enabled,
        provider=cfg.provider,
        model=cfg.model,
        base_url=cfg.base_url,
        fallback_enabled=cfg.fallback_enabled,
        fallback_provider=cfg.fallback_provider,
        fallback_model=cfg.fallback_model,
        fallback_base_url=cfg.fallback_base_url,
        prompt=cfg.prompt,
        temperature=cfg.temperature,
        max_image_count=cfg.max_image_count,
        has_api_key=bool(str(cfg.api_key or "").strip()),
        has_fallback_api_key=bool(str(cfg.fallback_api_key or "").strip()),
    )


@router.put("/integrated/submit-ai-title", response_model=PipelineSubmitAiTitleOut)
def update_integrated_submit_ai_title(body: PipelineSubmitAiTitleUpdateIn):
    """更新「提交前 AI 改标题」配置（写入数据库）。"""
    cfg = update_submit_ai_title_config(
        enabled=body.enabled,
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
        api_key=body.api_key,
        fallback_enabled=body.fallback_enabled,
        fallback_provider=body.fallback_provider,
        fallback_model=body.fallback_model,
        fallback_base_url=body.fallback_base_url,
        fallback_api_key=body.fallback_api_key,
        prompt=body.prompt,
        temperature=body.temperature,
        max_image_count=body.max_image_count,
    )
    return PipelineSubmitAiTitleOut(
        enabled=cfg.enabled,
        provider=cfg.provider,
        model=cfg.model,
        base_url=cfg.base_url,
        fallback_enabled=cfg.fallback_enabled,
        fallback_provider=cfg.fallback_provider,
        fallback_model=cfg.fallback_model,
        fallback_base_url=cfg.fallback_base_url,
        prompt=cfg.prompt,
        temperature=cfg.temperature,
        max_image_count=cfg.max_image_count,
        has_api_key=bool(str(cfg.api_key or "").strip()),
        has_fallback_api_key=bool(str(cfg.fallback_api_key or "").strip()),
    )


@router.post("/integrated/submit-ai-title/test", response_model=PipelineSubmitAiTitleTestOut)
def test_integrated_submit_ai_title(body: PipelineSubmitAiTitleTestIn):
    """
    配置页测试：选某套图（selector）/某个商品（product_code），调用提交前 AI 标题生成。

    注意：该接口只做生成，不会改动任何发布页数据。
    """
    selector = str(body.selector or "").strip()
    if not selector:
        raise HTTPException(status_code=422, detail="selector is required")

    source: MaterialSource = "minio" if str(body.material_source or "").strip() == "minio" else "local"
    settings = load_yaml_settings()
    assets_root = settings.paths.resolve("assets_root")
    if source == "minio":
        from pdd_agent.integrations.minio.config import minio_cache_root, minio_configured

        if not minio_configured():
            raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
        assets_root = minio_cache_root()

    product_code = str(body.product_code or "").strip()
    logger.info(
        "submit-ai-title test start selector=%s product_code=%s material_source=%s",
        selector,
        product_code or "-",
        source,
    )
    assets = resolve_submit_ai_title_test_assets(
        selector,
        product_code=product_code,
        assets_root=assets_root,
    )
    if not assets:
        raise HTTPException(status_code=404, detail=f"未找到套图/商品：{selector}")
    if not assets.carousel_images:
        raise HTTPException(status_code=404, detail=f"商品目录无可用主图：{assets.product_code}")

    image_paths = [str(p) for p in assets.carousel_images]
    listing_info = {
        "product_code": assets.product_code,
        "merchant_code": assets.merchant_code,
        "category_keyword": str(body.category_keyword or "").strip(),
    }
    logger.info(
        "submit-ai-title test assets resolved product=%s images=%d",
        assets.product_code,
        len(image_paths),
    )
    result = generate_submit_ai_title(
        account_id="",
        label=f"{assets.product_code}/{assets.image_set or selector}",
        image_paths=image_paths,
        listing_info=listing_info,
        current_title=str(body.current_title or "").strip(),
    )
    logger.info(
        "submit-ai-title test done applied=%s reason=%s source=%s",
        bool(result.get("applied")),
        str(result.get("reason") or "-"),
        str(result.get("source") or "-"),
    )
    return PipelineSubmitAiTitleTestOut(
        ok=bool(result.get("ok")),
        applied=bool(result.get("applied")),
        reason=str(result.get("reason") or ""),
        source=str(result.get("source") or ""),
        title=str(result.get("title") or ""),
        images_used=[str(x) for x in (result.get("images_used") or [])],
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
            primary_style_first_test=body.primary_style_first_test,
            paren_size_as_product_type=body.paren_size_as_product_type,
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
            listing_per_batch_lt_traffic_activity_enabled=body.listing_per_batch_lt_traffic_activity_enabled,
            listing_per_batch_promote_lt_success_only_enabled=body.listing_per_batch_promote_lt_success_only_enabled,
            delist_spec_code_search_enabled=body.delist_spec_code_search_enabled,
            activity_limited_time_success_only=body.activity_limited_time_success_only,
            activity_traffic_batch_enabled=body.activity_traffic_batch_enabled,
            activity_traffic_batch_size=body.activity_traffic_batch_size,
            per_batch_limited_time_chunk_size=body.per_batch_limited_time_chunk_size,
            batch_limited_time_auto_retry_enabled=body.batch_limited_time_auto_retry_enabled,
            batch_limited_time_auto_retry_max_attempts=body.batch_limited_time_auto_retry_max_attempts,
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
            primary_style_first_test=body.primary_style_first_test,
            paren_size_as_product_type=body.paren_size_as_product_type,
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
            listing_per_batch_lt_traffic_activity_enabled=body.listing_per_batch_lt_traffic_activity_enabled,
            listing_per_batch_promote_lt_success_only_enabled=body.listing_per_batch_promote_lt_success_only_enabled,
            store_sequential_enabled=body.store_sequential_enabled,
            delist_spec_code_search_enabled=body.delist_spec_code_search_enabled,
            activity_limited_time_success_only=body.activity_limited_time_success_only,
            activity_traffic_batch_enabled=body.activity_traffic_batch_enabled,
            activity_traffic_batch_size=body.activity_traffic_batch_size,
            per_batch_limited_time_chunk_size=body.per_batch_limited_time_chunk_size,
            batch_limited_time_auto_retry_enabled=body.batch_limited_time_auto_retry_enabled,
            batch_limited_time_auto_retry_max_attempts=body.batch_limited_time_auto_retry_max_attempts,
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


@router.get(
    "/integrated/{pipeline_id}/batch-product-stages",
    response_model=IntegratedPipelineBatchProductStageListResponse,
)
def list_integrated_batch_product_stages(pipeline_id: str, batch_index: int | None = None):
    """查询整合链路分批模式下每批每商品的阶段状态。"""
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    data = get_pipeline(pipeline_id)
    if not data:
        raise HTTPException(status_code=404, detail="pipeline not found")
    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
        list_pipeline_batch_product_stages,
    )

    items = list_pipeline_batch_product_stages(
        pipeline_id=pipeline_id,
        batch_index=batch_index,
    )
    return IntegratedPipelineBatchProductStageListResponse(
        pipeline_id=pipeline_id,
        items=items,
        total=len(items),
    )


@router.patch(
    "/integrated/{pipeline_id}/batch-product-stages",
    response_model=IntegratedPipelineBatchProductStagePatchResponse,
)
def patch_integrated_batch_product_stage(
    pipeline_id: str,
    body: IntegratedPipelineBatchProductStagePatchRequest,
):
    """精准更新原链路某一商品的每批阶段状态（不影响同批其它商品）。"""
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    data = get_pipeline(pipeline_id)
    if not data:
        raise HTTPException(status_code=404, detail="pipeline not found")
    from pdd_agent.api.services.failure_log_attach_retry.bridge import (
        patch_batch_product_stage,
    )

    try:
        result = patch_batch_product_stage(
            pipeline_id=pipeline_id,
            batch_index=body.batch_index,
            product_selector=body.product_selector,
            pdd_product_id=body.pdd_product_id,
            mapping_id=body.mapping_id,
            listing_status=body.listing_status,
            listing_error=body.listing_error,
            limited_time_status=body.limited_time_status,
            limited_time_error=body.limited_time_error,
            promotion_status=body.promotion_status,
            promotion_error=body.promotion_error,
            activity_1_status=body.activity_1_status,
            activity_1_error=body.activity_1_error,
            activity_2_status=body.activity_2_status,
            activity_2_error=body.activity_2_error,
            set_pdd_product_id=body.set_pdd_product_id,
            set_mapping_id=body.set_mapping_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IntegratedPipelineBatchProductStagePatchResponse(**result)


@router.get("/integrated/{pipeline_id}", response_model=IntegratedPipelineResponse)
def get_integrated(pipeline_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    data = get_pipeline(pipeline_id)
    if not data:
        raise HTTPException(status_code=404, detail="pipeline not found")
    return IntegratedPipelineResponse(**data)


@router.post("/integrated/{pipeline_id}/late-retry-failed", response_model=PipelineLateRetryStartResponse)
def late_retry_failed_integrated(pipeline_id: str, body: PipelineLateRetryStartRequest | None = None):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    from pdd_agent.api.services.pipeline_late_retry_policy import start_late_retry_failed

    body = body or PipelineLateRetryStartRequest()
    try:
        data = start_late_retry_failed(
            pipeline_id,
            selectors=list(body.selectors or []),
            deadline_buffer_minutes=body.deadline_buffer_minutes,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail == "pipeline_not_found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return PipelineLateRetryStartResponse(**data)


@router.get(
    "/integrated/{pipeline_id}/batch-limited-time-retry/eligibility",
    response_model=PipelineBatchLimitedTimeRetryEligibilityOut,
)
def batch_limited_time_retry_eligibility(pipeline_id: str, batch_index: int):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    data = get_pipeline(pipeline_id)
    if not data:
        raise HTTPException(status_code=404, detail="pipeline not found")
    from pdd_agent.db.repositories import get_integrated_pipeline
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
        evaluate_batch_limited_time_retry_eligibility,
    )

    row = get_integrated_pipeline(pipeline_id)
    if not row:
        raise HTTPException(status_code=404, detail="pipeline not found")
    result = evaluate_batch_limited_time_retry_eligibility(row, int(batch_index))
    return PipelineBatchLimitedTimeRetryEligibilityOut(**result)


@router.post(
    "/integrated/{pipeline_id}/batch-limited-time-retry",
    response_model=PipelineBatchLimitedTimeRetryStartResponse,
)
def start_batch_limited_time_retry_integrated(
    pipeline_id: str,
    body: PipelineBatchLimitedTimeRetryStartRequest,
):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    data = get_pipeline(pipeline_id)
    if not data:
        raise HTTPException(status_code=404, detail="pipeline not found")
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
        start_batch_limited_time_retry,
    )

    try:
        result = start_batch_limited_time_retry(pipeline_id, batch_index=int(body.batch_index))
    except ValueError as exc:
        detail = str(exc)
        if detail == "pipeline_not_found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return PipelineBatchLimitedTimeRetryStartResponse(**result)


@router.post(
    "/integrated/{pipeline_id}/batch-limited-time-retry/all",
    response_model=PipelineBatchLimitedTimeRetryAllStartResponse,
)
def start_all_batch_limited_time_retry_integrated(pipeline_id: str):
    """一键重跑当前链路全部「上架成功 + 限时失败」批次（串行排队）。"""
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    data = get_pipeline(pipeline_id)
    if not data:
        raise HTTPException(status_code=404, detail="pipeline not found")
    from pdd_agent.api.services.pipeline_batch_limited_time_retry_bridge import (
        start_all_batch_limited_time_retries,
    )

    try:
        result = start_all_batch_limited_time_retries(pipeline_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "pipeline_not_found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return PipelineBatchLimitedTimeRetryAllStartResponse(**result)


@router.put(
    "/integrated/{pipeline_id}/per-batch-lt-chunks",
    response_model=PerBatchLtChunkSettingsOut,
)
def update_per_batch_lt_chunk_settings_integrated(
    pipeline_id: str,
    body: PerBatchLtChunkSettingsUpdateIn,
):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    row = get_integrated_pipeline(str(pipeline_id or "").strip())
    if not row:
        raise HTTPException(status_code=404, detail="pipeline not found")
    from pdd_agent.api.services.pipeline_per_batch_lt_chunks.bridge import (
        update_per_batch_lt_chunk_settings,
    )

    try:
        result = update_per_batch_lt_chunk_settings(
            row,
            enabled=body.enabled,
            chunk_size=body.chunk_size,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail == "not_standard_per_batch_lt_pipeline":
            raise HTTPException(status_code=400, detail=detail) from exc
        if detail == "chunk_sequence_in_progress":
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return PerBatchLtChunkSettingsOut(**result)


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

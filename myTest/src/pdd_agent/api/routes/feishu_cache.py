"""飞书数据缓存管理。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.feishu_cache import FeishuClearCacheOut
from pdd_agent.api.schemas.feishu_inspect import (
    FeishuInspectListingPricesIn,
    FeishuInspectListingPricesOut,
)
from pdd_agent.api.services.pipeline_service import get_pipeline
from pdd_agent.integrations.feishu.cache import clear_feishu_data_caches
from pdd_agent.integrations.feishu.listing_feishu_inspect import inspect_listing_feishu_prices
from pdd_agent.integrations.feishu.listing_feishu_inspect_store import (
    load_pipeline_feishu_inspect,
    merchant_codes_for_pipeline,
    save_pipeline_feishu_inspect,
)

router = APIRouter(prefix="/feishu", tags=["feishu-cache"])


@router.post("/clear-cache", response_model=FeishuClearCacheOut)
def clear_feishu_cache():
    """一键清空当前 worker 的飞书商品表 / 比价定价 / 上架快照等内存缓存。"""
    return FeishuClearCacheOut(**clear_feishu_data_caches())


@router.post("/inspect-listing-prices", response_model=FeishuInspectListingPricesOut)
def inspect_feishu_listing_prices(body: FeishuInspectListingPricesIn):
    """按商品编码实时读取飞书「拼多多比价定价」并返回解析后的字段（调试用）。"""
    pipeline_id = str(body.pipeline_id or "").strip()
    codes = list(body.codes or [])

    if pipeline_id and not codes:
        pipeline = get_pipeline(pipeline_id)
        if not pipeline:
            raise HTTPException(status_code=404, detail="pipeline not found")
        codes = merchant_codes_for_pipeline(pipeline) or list(pipeline.get("product_codes") or [])

    if not codes:
        raise HTTPException(status_code=422, detail="codes is required")

    if pipeline_id and not body.force_refresh:
        cached = load_pipeline_feishu_inspect(pipeline_id)
        if cached:
            return FeishuInspectListingPricesOut(**cached, from_cache=True)

    result = inspect_listing_feishu_prices(codes, force_refresh=body.force_refresh)
    if pipeline_id:
        result = save_pipeline_feishu_inspect(pipeline_id, result)
    return FeishuInspectListingPricesOut(**result, from_cache=False)

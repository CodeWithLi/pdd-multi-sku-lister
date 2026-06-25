"""飞书数据缓存管理。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.feishu_cache import (
    FeishuClearCacheOut,
    FeishuFailureLogSettingsOut,
    FeishuFailureLogSettingsUpdateIn,
)
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
from pdd_agent.integrations.feishu.bitable import find_view_id_by_name, resolve_table_field_name
from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import load_feishu_config, save_pdd_failure_log_enabled_to_config
from pdd_agent.integrations.feishu.pdd_price_compare_sync import _field_text, resolve_pdd_price_compare_table_id

router = APIRouter(prefix="/feishu", tags=["feishu-cache"])


@router.post("/clear-cache", response_model=FeishuClearCacheOut)
def clear_feishu_cache():
    """一键清空当前 worker 的飞书商品表 / 比价定价 / 上架快照等内存缓存。"""
    return FeishuClearCacheOut(**clear_feishu_data_caches())


@router.get("/failure-log-settings", response_model=FeishuFailureLogSettingsOut)
def get_failure_log_settings():
    """读取「全平台发布日志表（失败）」回写开关。"""
    cfg = load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    return FeishuFailureLogSettingsOut(
        failure_log_enabled=bool(pdd_cfg.failure_log_enabled),
        failure_table_name=str(pdd_cfg.failure_table_name or ""),
        failure_table_id=str(pdd_cfg.failure_table_id or ""),
    )


@router.put("/failure-log-settings", response_model=FeishuFailureLogSettingsOut)
def update_failure_log_settings(body: FeishuFailureLogSettingsUpdateIn):
    """更新「全平台发布日志表（失败）」回写开关（写入 feishu.yaml）。"""
    save_pdd_failure_log_enabled_to_config(body.failure_log_enabled)
    return get_failure_log_settings()


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


@router.get("/inspect-price-compare-bag-view")
def inspect_price_compare_bag_view(limit: int = 30):
    """读取拼多多比价定价表「笔袋」视图，用于校验视图连通性。"""
    cfg = load_feishu_config()
    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token:
        raise HTTPException(status_code=422, detail="未配置 bitable_app_token")

    api = FeishuClient(cfg)
    table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
    if not table_id:
        raise HTTPException(status_code=422, detail="未找到飞书表「拼多多比价定价」")

    view_name = str(cfg.pdd_price_compare.listing_required_view_name or "").strip() or "笔袋"
    view_id = str(cfg.pdd_price_compare.listing_required_view_id or "").strip()
    if not view_id:
        view_id = find_view_id_by_name(api, app_token, table_id, view_name)
    if not view_id:
        raise HTTPException(status_code=422, detail=f"未找到视图：{view_name}")

    code_field = resolve_table_field_name(
        api,
        app_token,
        table_id,
        cfg.pdd_product_catalog.field_names.product_code,
    )
    resp = api.request(
        "GET",
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        params={
            "view_id": view_id,
            "page_size": max(1, min(int(limit), 200)),
        },
        prefer_user_token=True,
    )
    items = list((resp.get("data") or {}).get("items") or [])
    rows: list[dict[str, str]] = []
    for item in items:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        rows.append(
            {
                "record_id": str(item.get("record_id") or ""),
                "merchant_code": _field_text(fields, code_field),
                "raw_code": str(fields.get(code_field) or ""),
            }
        )
    return {
        "ok": True,
        "table_name": cfg.pdd_price_compare.table_name,
        "table_id": table_id,
        "view_name": view_name,
        "view_id": view_id,
        "count": len(rows),
        "rows": rows,
    }

"""飞书数据缓存管理。"""

from __future__ import annotations

from fastapi import APIRouter

from dy_agent.api.schemas.feishu_cache import (
    FeishuClearCacheOut,
    FeishuFailureLogSettingsOut,
    FeishuFailureLogSettingsUpdateIn,
)
from dy_agent.integrations.feishu.cache import clear_feishu_data_caches
from dy_agent.integrations.feishu.config import load_feishu_config, save_pdd_failure_log_enabled_to_config

router = APIRouter(prefix="/feishu", tags=["feishu-cache"])


@router.post("/clear-cache", response_model=FeishuClearCacheOut)
def clear_feishu_cache():
    """清空当前 worker 的飞书商品表 / 比价定价 / 上架快照等内存缓存。"""
    return FeishuClearCacheOut(**clear_feishu_data_caches())


@router.get("/failure-log-settings", response_model=FeishuFailureLogSettingsOut)
def get_failure_log_settings():
    cfg = load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    return FeishuFailureLogSettingsOut(
        failure_log_enabled=bool(pdd_cfg.failure_log_enabled),
        failure_table_name=str(pdd_cfg.failure_table_name or ""),
        failure_table_id=str(pdd_cfg.failure_table_id or ""),
    )


@router.put("/failure-log-settings", response_model=FeishuFailureLogSettingsOut)
def update_failure_log_settings(body: FeishuFailureLogSettingsUpdateIn):
    save_pdd_failure_log_enabled_to_config(body.failure_log_enabled)
    return get_failure_log_settings()

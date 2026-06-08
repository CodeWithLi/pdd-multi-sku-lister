"""配置相关接口：摘要 + 店铺 CRUD。"""

from fastapi import APIRouter, Query

from pdd_agent.api.schemas.config import (
    AccountCreateIn,
    AccountDetailOut,
    AccountOut,
    AccountUpdateIn,
    ConfigSummaryOut,
    RuntimeConfigOut,
    RuntimeConfigUpdateIn,
)
from pdd_agent.api.services import config_service

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/summary", response_model=ConfigSummaryOut)
def config_summary():
    """系统配置摘要（不含密钥）。"""
    return config_service.get_config_summary()


@router.get("/runtime", response_model=RuntimeConfigOut)
def config_runtime():
    """运行参数配置：路径、浏览器、默认上下架规则。"""
    return config_service.get_runtime_config()


@router.put("/runtime", response_model=RuntimeConfigOut)
def config_runtime_update(body: RuntimeConfigUpdateIn):
    """保存运行参数配置到 settings.yaml。"""
    return config_service.update_runtime_config(body)


@router.get("/accounts", response_model=list[AccountOut])
def config_accounts(enabled_only: bool = Query(False, description="仅返回 enabled 店铺")):
    """店铺列表。"""
    return config_service.list_accounts(enabled_only=enabled_only)


@router.get("/accounts/{account_id}", response_model=AccountDetailOut)
def config_account_detail(account_id: str):
    """店铺详情（含密码，供编辑表单）。"""
    return config_service.get_account_detail(account_id)


@router.post("/accounts", response_model=AccountDetailOut, status_code=201)
def config_account_create(body: AccountCreateIn):
    """新增店铺。"""
    return config_service.create_account(body)


@router.put("/accounts/{account_id}", response_model=AccountDetailOut)
def config_account_update(account_id: str, body: AccountUpdateIn):
    """修改店铺；password 留空则不修改原密码。"""
    return config_service.update_account(account_id, body)


@router.delete("/accounts/{account_id}", status_code=204)
def config_account_delete(account_id: str):
    """删除店铺。"""
    config_service.delete_account(account_id)

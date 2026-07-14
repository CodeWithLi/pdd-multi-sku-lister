"""配置相关接口。"""

from fastapi import APIRouter, Query

from dy_agent.api.schemas.config import (
    AccountCreateIn,
    AccountDetailOut,
    AccountOut,
    AccountUpdateIn,
    ConfigSummaryOut,
    RuntimeConfigOut,
    RuntimeConfigUpdateIn,
)
from dy_agent.api.services import config_service

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/summary", response_model=ConfigSummaryOut)
def config_summary():
    return config_service.get_config_summary()


@router.get("/runtime", response_model=RuntimeConfigOut)
def config_runtime():
    return config_service.get_runtime_config()


@router.put("/runtime", response_model=RuntimeConfigOut)
def config_runtime_update(body: RuntimeConfigUpdateIn):
    return config_service.update_runtime_config(body)


@router.get("/accounts", response_model=list[AccountOut])
def config_accounts(enabled_only: bool = Query(False)):
    return config_service.list_accounts(enabled_only=enabled_only)


@router.get("/accounts/{account_id}", response_model=AccountDetailOut)
def config_account_detail(account_id: str):
    return config_service.get_account_detail(account_id)


@router.post("/accounts", response_model=AccountDetailOut, status_code=201)
def config_account_create(body: AccountCreateIn):
    return config_service.create_account(body)


@router.put("/accounts/{account_id}", response_model=AccountDetailOut)
def config_account_update(account_id: str, body: AccountUpdateIn):
    return config_service.update_account(account_id, body)


@router.delete("/accounts/{account_id}", status_code=204)
def config_account_delete(account_id: str):
    config_service.delete_account(account_id)

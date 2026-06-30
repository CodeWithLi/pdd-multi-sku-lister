"""店铺运营周期与意图队列 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from pdd_agent.api.services.commerce_dispatch import (
    cancel_commerce_intent,
    cancel_commerce_intents,
    get_account_lifecycle_status,
    get_commerce_overview,
    list_pending_intents,
    reconcile_commerce_state,
    try_dispatch_pending_for_account,
)
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/commerce", tags=["commerce"])


class CommerceIntentCancelIn(BaseModel):
    intent_ids: list[str] = Field(default_factory=list)
    account_id: str = ""


@router.get("/overview")
def commerce_overview(intent_limit: int = Query(default=100, ge=1, le=200)):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    return get_commerce_overview(intent_limit=intent_limit)


@router.get("/lifecycle/{account_id}")
def get_lifecycle(account_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    row = get_account_lifecycle_status(account_id)
    if not row:
        return {"account_id": account_id, "lifecycle_status": "none"}
    return row


@router.get("/intents")
def list_intents(
    account_id: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    return {"items": list_pending_intents(account_id=account_id, limit=limit)}


@router.post("/dispatch/{account_id}")
def dispatch_account(account_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    outcome = try_dispatch_pending_for_account(account_id)
    if not outcome:
        return {"dispatched": False, "message": "无待派发意图或店铺仍有活跃周期"}
    return outcome


@router.post("/dispatch")
def dispatch_all(limit: int = Query(default=20, ge=1, le=100)):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    result = reconcile_commerce_state(dispatch_limit=limit)
    return {
        "count": result.get("dispatched_count", 0),
        "items": result.get("dispatched") or [],
        "nudged": result.get("nudged", 0),
        "synced": result.get("synced", 0),
    }


@router.post("/reconcile")
def reconcile_commerce(dispatch_limit: int = Query(default=30, ge=1, le=100)):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    return reconcile_commerce_state(dispatch_limit=dispatch_limit)


@router.post("/intents/{intent_id}/cancel")
def cancel_intent(intent_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    outcome = cancel_commerce_intent(intent_id)
    if not outcome.get("ok"):
        raise HTTPException(status_code=400, detail=str(outcome.get("error") or "cancel_failed"))
    return outcome


@router.post("/intents/cancel")
def cancel_intents(body: CommerceIntentCancelIn):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用")
    outcome = cancel_commerce_intents(
        intent_ids=body.intent_ids,
        account_id=body.account_id,
    )
    if not outcome.get("ok"):
        raise HTTPException(status_code=400, detail="没有可取消的排队任务")
    return outcome

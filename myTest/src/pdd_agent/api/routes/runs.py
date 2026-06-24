"""任务运行记录查询与 AI 解读。"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.tasks import (
    RunInterpretResponse,
    RunListResponse,
    RunPlatformGuardOut,
    RunRecordOut,
)
from pdd_agent.core.config import get_env_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.skills.interpret import interpret_run
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)
router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=RunListResponse)
def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    account_id: str = "",
    agent: str = "",
    status: str = "",
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    product_code: str = "",
):
    """分页查询任务记录。"""
    store = TaskRunStore()
    if limit is not None:
        page = 1
        page_size = limit
    items, total = store.search_runs(
        page=page,
        page_size=page_size,
        account_id=account_id.strip(),
        agent=agent.strip(),
        status=status.strip(),
        started_from=started_from,
        started_to=started_to,
        product_code=product_code.strip(),
    )
    return RunListResponse(
        items=[RunRecordOut.from_record(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{run_id}", response_model=RunRecordOut)
def get_run(run_id: str):
    """单条任务详情（含 result）。"""
    store = TaskRunStore()
    record = store.load(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return RunRecordOut.from_record(record)


@router.post("/{run_id}/interpret", response_model=RunInterpretResponse)
def interpret_run_record(run_id: str):
    """AI 解读操作记录，用运营可读的中文说明原因与处理建议。"""
    env = get_env_settings()
    if not env.llm_api_key:
        raise HTTPException(
            status_code=503,
            detail="未配置 LLM_API_KEY，请在 myTest/.env 中填写智谱/通义等 API Key 后重启后台",
        )

    store = TaskRunStore()
    record = store.load(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")

    try:
        text = interpret_run(record)
    except Exception as exc:
        logger.exception("interpret failed run_id=%s", run_id)
        raise HTTPException(status_code=502, detail=f"AI 解读失败: {exc}") from exc

    return RunInterpretResponse(
        run_id=run_id,
        interpretation=text,
        llm_model=env.llm_model,
    )


@router.get("/{run_id}/platform-guard", response_model=RunPlatformGuardOut)
def get_run_platform_guard(run_id: str):
    """按 run_id 返回平台守卫检查明细（输入编码、命中、缺失、视图信息）。"""
    store = TaskRunStore()
    record = store.load(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")

    payload = record.result if isinstance(record.result, dict) else {}
    guard = payload.get("platform_guard") if isinstance(payload.get("platform_guard"), dict) else {}

    inferred_missing: list[str] = []
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("reason") or "").strip() != "platform_not_applicable":
            continue
        code = str(row.get("platform_listing_code") or row.get("merchant_code") or "").strip()
        if code:
            inferred_missing.append(code)

    input_codes = [str(x).strip() for x in list(guard.get("input_codes") or []) if str(x).strip()]
    matched_codes = [str(x).strip() for x in list(guard.get("matched_codes") or []) if str(x).strip()]
    missing_codes = [str(x).strip() for x in list(guard.get("missing_codes") or []) if str(x).strip()]
    if not missing_codes and inferred_missing:
        missing_codes = list(dict.fromkeys(inferred_missing))
    if not input_codes and missing_codes:
        input_codes = list(dict.fromkeys(missing_codes))

    has_guard_data = bool(guard) or bool(inferred_missing)
    return RunPlatformGuardOut(
        run_id=run_id,
        has_guard_data=has_guard_data,
        input_codes=input_codes,
        matched_codes=matched_codes,
        missing_codes=missing_codes,
        ok=guard.get("ok") if isinstance(guard, dict) else None,
        reason=str(guard.get("reason") or ""),
        error=str(guard.get("error") or ""),
        view_name=str(guard.get("view_name") or ""),
        view_id=str(guard.get("view_id") or ""),
        table_id=str(guard.get("table_id") or ""),
    )

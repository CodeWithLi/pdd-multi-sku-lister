"""任务运行记录查询与 AI 解读。"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.tasks import RunInterpretResponse, RunListResponse, RunRecordOut
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

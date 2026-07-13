"""运行记录查询。"""

from fastapi import APIRouter, HTTPException, Query

from dy_agent.storage import TaskRunStore

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
def list_runs(
    limit: int = Query(50, ge=1, le=200),
    account_id: str = "",
    status: str = "",
):
    records = TaskRunStore().list_runs(limit=200)
    if account_id:
        records = [r for r in records if r.account_id == account_id]
    if status:
        records = [r for r in records if r.status.value == status]
    return {
        "items": [r.model_dump(mode="json") for r in records[:limit]],
        "total": len(records),
    }


@router.get("/{run_id}")
def get_run(run_id: str):
    record = TaskRunStore().load(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="run not found")
    return record.model_dump(mode="json")

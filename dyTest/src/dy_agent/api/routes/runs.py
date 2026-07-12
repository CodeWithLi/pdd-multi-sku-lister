"""运行记录查询。"""

from fastapi import APIRouter, HTTPException

from dy_agent.storage import TaskRunStore

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
def list_runs(limit: int = 50):
    records = TaskRunStore().list_runs(limit=limit)
    return [r.model_dump(mode="json") for r in records]


@router.get("/{run_id}")
def get_run(run_id: str):
    record = TaskRunStore().load(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="run not found")
    return record.model_dump(mode="json")

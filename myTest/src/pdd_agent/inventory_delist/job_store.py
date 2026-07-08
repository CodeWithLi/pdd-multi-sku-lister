"""库存下架 — 任务状态持久化。"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from pdd_agent.inventory_delist.config import state_file_path

JobStatus = Literal["pending", "running", "completed", "failed", "canceled"]
AccountDelistStatus = Literal["pending", "queued", "running", "completed", "failed", "skipped"]


@dataclass
class AccountDelistTask:
    account_id: str
    status: AccountDelistStatus = "pending"
    run_id: str = ""
    candidate_codes: list[str] = field(default_factory=list)
    target_count: int = 0
    deleted_mapping_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class InventoryDelistJob:
    job_id: str
    status: JobStatus = "pending"
    trigger: str = "manual"
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    account_ids: list[str] = field(default_factory=list)
    execution_mode: str = "parallel"
    common_on_sale_codes: list[str] = field(default_factory=list)
    negative_inventory_codes: list[str] = field(default_factory=list)
    per_account: list[AccountDelistTask] = field(default_factory=list)
    delist_dry_run: bool = False
    analysis_snapshot: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error: str = ""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_state() -> dict[str, Any]:
    path = state_file_path()
    if not path.is_file():
        return {"jobs": [], "last_scheduled_run_at": ""}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except (OSError, json.JSONDecodeError):
        pass
    return {"jobs": [], "last_scheduled_run_at": ""}


def _save_state(state: dict[str, Any]) -> None:
    path = state_file_path()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def create_job(
    *,
    account_ids: list[str],
    execution_mode: str,
    analysis_snapshot: dict[str, Any],
    trigger: str = "manual",
) -> InventoryDelistJob:
    job_id = f"inv_delist_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    per_account_rows = analysis_snapshot.get("per_account") or []
    account_tasks = [
        AccountDelistTask(
            account_id=str(row.get("account_id") or ""),
            candidate_codes=list(row.get("delist_candidate_codes") or []),
            target_count=len(row.get("delist_candidate_codes") or []),
            status="skipped" if not row.get("delist_candidate_codes") else "pending",
        )
        for row in per_account_rows
        if str(row.get("account_id") or "").strip()
    ]
    job = InventoryDelistJob(
        job_id=job_id,
        status="pending",
        trigger=trigger,
        created_at=_now_iso(),
        account_ids=list(account_ids),
        execution_mode=execution_mode,
        common_on_sale_codes=list(analysis_snapshot.get("common_on_sale_codes") or []),
        negative_inventory_codes=list(analysis_snapshot.get("negative_inventory_codes") or []),
        per_account=account_tasks,
        delist_dry_run=bool(analysis_snapshot.get("delist_dry_run")),
        analysis_snapshot=dict(analysis_snapshot),
    )
    state = _load_state()
    jobs = list(state.get("jobs") or [])
    jobs.insert(0, _job_to_dict(job))
    state["jobs"] = jobs[:50]
    _save_state(state)
    return job


def get_job(job_id: str) -> InventoryDelistJob | None:
    state = _load_state()
    for raw in state.get("jobs") or []:
        if isinstance(raw, dict) and str(raw.get("job_id") or "") == job_id:
            return _job_from_dict(raw)
    return None


def list_jobs(*, limit: int = 20) -> list[InventoryDelistJob]:
    state = _load_state()
    jobs: list[InventoryDelistJob] = []
    for raw in (state.get("jobs") or [])[:limit]:
        if isinstance(raw, dict):
            jobs.append(_job_from_dict(raw))
    return jobs


def update_job(job: InventoryDelistJob) -> None:
    state = _load_state()
    jobs = list(state.get("jobs") or [])
    payload = _job_to_dict(job)
    replaced = False
    for index, raw in enumerate(jobs):
        if isinstance(raw, dict) and str(raw.get("job_id") or "") == job.job_id:
            jobs[index] = payload
            replaced = True
            break
    if not replaced:
        jobs.insert(0, payload)
    state["jobs"] = jobs[:50]
    _save_state(state)


def get_last_scheduled_run_at() -> str:
    return str(_load_state().get("last_scheduled_run_at") or "")


def set_last_scheduled_run_at(value: str) -> None:
    state = _load_state()
    state["last_scheduled_run_at"] = value
    _save_state(state)


def _job_to_dict(job: InventoryDelistJob) -> dict[str, Any]:
    data = asdict(job)
    data["per_account"] = [asdict(row) for row in job.per_account]
    return data


def _job_from_dict(raw: dict[str, Any]) -> InventoryDelistJob:
    per_account = [
        AccountDelistTask(**row)
        for row in (raw.get("per_account") or [])
        if isinstance(row, dict)
    ]
    return InventoryDelistJob(
        job_id=str(raw.get("job_id") or ""),
        status=str(raw.get("status") or "pending"),  # type: ignore[arg-type]
        trigger=str(raw.get("trigger") or "manual"),
        created_at=str(raw.get("created_at") or ""),
        started_at=str(raw.get("started_at") or ""),
        finished_at=str(raw.get("finished_at") or ""),
        account_ids=list(raw.get("account_ids") or []),
        execution_mode=str(raw.get("execution_mode") or "parallel"),
        common_on_sale_codes=list(raw.get("common_on_sale_codes") or []),
        negative_inventory_codes=list(raw.get("negative_inventory_codes") or []),
        per_account=per_account,
        delist_dry_run=bool(raw.get("delist_dry_run")),
        analysis_snapshot=dict(raw.get("analysis_snapshot") or {}),
        message=str(raw.get("message") or ""),
        error=str(raw.get("error") or ""),
    )

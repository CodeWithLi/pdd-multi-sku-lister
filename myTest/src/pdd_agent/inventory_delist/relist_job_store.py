"""库存恢复上架 — 任务状态持久化。"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from pdd_agent.inventory_delist.config import state_file_path

RelistJobStatus = Literal["pending", "running", "completed", "failed", "canceled"]
AccountRelistStatus = Literal["pending", "queued", "running", "completed", "failed", "skipped"]


@dataclass
class AccountRelistTask:
    account_id: str
    status: AccountRelistStatus = "pending"
    run_id: str = ""
    candidate_codes: list[str] = field(default_factory=list)
    code_record_ids: dict[str, list[str]] = field(default_factory=dict)
    code_pdd_product_ids: dict[str, str] = field(default_factory=dict)
    target_count: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class InventoryRelistJob:
    job_id: str
    status: RelistJobStatus = "pending"
    trigger: str = "manual"
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    account_ids: list[str] = field(default_factory=list)
    execution_mode: str = "parallel"
    relist_candidates_count: int = 0
    per_account: list[AccountRelistTask] = field(default_factory=list)
    relist_dry_run: bool = False
    analysis_snapshot: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error: str = ""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _relist_state_path():
    return state_file_path().with_name("inventory_relist_state.json")


def _load_state() -> dict[str, Any]:
    path = _relist_state_path()
    if not path.is_file():
        return {"jobs": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except (OSError, json.JSONDecodeError):
        pass
    return {"jobs": []}


def _save_state(state: dict[str, Any]) -> None:
    path = _relist_state_path()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _task_from_dict(raw: dict) -> AccountRelistTask:
    return AccountRelistTask(
        account_id=str(raw.get("account_id") or ""),
        status=str(raw.get("status") or "pending"),  # type: ignore[arg-type]
        run_id=str(raw.get("run_id") or ""),
        candidate_codes=list(raw.get("candidate_codes") or []),
        code_record_ids=dict(raw.get("code_record_ids") or {}),
        code_pdd_product_ids=dict(raw.get("code_pdd_product_ids") or {}),
        target_count=int(raw.get("target_count") or 0),
        warnings=list(raw.get("warnings") or []),
        error=str(raw.get("error") or ""),
    )


def _job_from_dict(raw: dict) -> InventoryRelistJob:
    return InventoryRelistJob(
        job_id=str(raw.get("job_id") or ""),
        status=str(raw.get("status") or "pending"),  # type: ignore[arg-type]
        trigger=str(raw.get("trigger") or "manual"),
        created_at=str(raw.get("created_at") or ""),
        started_at=str(raw.get("started_at") or ""),
        finished_at=str(raw.get("finished_at") or ""),
        account_ids=list(raw.get("account_ids") or []),
        execution_mode=str(raw.get("execution_mode") or "parallel"),
        relist_candidates_count=int(raw.get("relist_candidates_count") or 0),
        per_account=[_task_from_dict(row) for row in (raw.get("per_account") or []) if isinstance(row, dict)],
        relist_dry_run=bool(raw.get("relist_dry_run")),
        analysis_snapshot=dict(raw.get("analysis_snapshot") or {}),
        message=str(raw.get("message") or ""),
        error=str(raw.get("error") or ""),
    )


def _job_to_dict(job: InventoryRelistJob) -> dict[str, Any]:
    data = asdict(job)
    data["per_account"] = [asdict(row) for row in job.per_account]
    return data


def create_relist_job(
    *,
    account_ids: list[str],
    execution_mode: str,
    analysis_snapshot: dict[str, Any],
    trigger: str = "manual",
) -> InventoryRelistJob:
    job_id = f"inv_relist_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    per_account_rows: list[AccountRelistTask] = []
    for row in analysis_snapshot.get("per_account_tasks") or []:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("account_id") or "").strip()
        if not aid:
            continue
        codes = list(row.get("candidate_codes") or [])
        per_account_rows.append(
            AccountRelistTask(
                account_id=aid,
                candidate_codes=codes,
                code_record_ids=dict(row.get("code_record_ids") or {}),
                code_pdd_product_ids=dict(row.get("code_pdd_product_ids") or {}),
                target_count=len(codes),
                status="skipped" if not codes else "pending",
            )
        )
    job = InventoryRelistJob(
        job_id=job_id,
        status="pending",
        trigger=trigger,
        created_at=_now_iso(),
        account_ids=list(account_ids),
        execution_mode=execution_mode,
        relist_candidates_count=int(analysis_snapshot.get("relist_candidates_count") or 0),
        per_account=per_account_rows,
        relist_dry_run=bool(analysis_snapshot.get("relist_dry_run")),
        analysis_snapshot=dict(analysis_snapshot),
    )
    state = _load_state()
    jobs = list(state.get("jobs") or [])
    jobs.insert(0, _job_to_dict(job))
    state["jobs"] = jobs[:50]
    _save_state(state)
    return job


def get_relist_job(job_id: str) -> InventoryRelistJob | None:
    for raw in _load_state().get("jobs") or []:
        if isinstance(raw, dict) and str(raw.get("job_id") or "") == job_id:
            return _job_from_dict(raw)
    return None


def list_relist_jobs(*, limit: int = 20) -> list[InventoryRelistJob]:
    jobs: list[InventoryRelistJob] = []
    for raw in (_load_state().get("jobs") or [])[:limit]:
        if isinstance(raw, dict):
            jobs.append(_job_from_dict(raw))
    return jobs


def update_relist_job(job: InventoryRelistJob) -> None:
    state = _load_state()
    jobs = list(state.get("jobs") or [])
    payload = _job_to_dict(job)
    for idx, raw in enumerate(jobs):
        if isinstance(raw, dict) and str(raw.get("job_id") or "") == job.job_id:
            jobs[idx] = payload
            break
    else:
        jobs.insert(0, payload)
    state["jobs"] = jobs[:50]
    _save_state(state)

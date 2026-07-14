"""任务运行记录持久化（MySQL 优先，JSON 降级）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dy_agent.core.config import load_yaml_settings
from dy_agent.core.json_safe import json_safe
from dy_agent.db.models import RunRecordORM
from dy_agent.db.session import is_database_available, session_scope
from dy_agent.domain.enums import AgentKind, RunStatus, TaskPhase
from dy_agent.domain.models import RunRecord

_DB_MESSAGE_MAX = 2000


def _clamp_message(message: str, limit: int = _DB_MESSAGE_MAX) -> str:
    text = str(message or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(共{len(text)}字)"


class TaskRunStore:
    def __init__(self, runs_root: Path | None = None) -> None:
        settings = load_yaml_settings()
        self._root = runs_root or settings.paths.resolve("runs_root")
        if not is_database_available():
            self._root.mkdir(parents=True, exist_ok=True)

    def create_run(self, agent: AgentKind, account_id: str) -> RunRecord:
        run = RunRecord(
            run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8],
            agent=agent,
            account_id=account_id,
            status=RunStatus.RUNNING,
            phase=TaskPhase.PLAN,
        )
        self.save(run)
        return run

    def path_for(self, run_id: str) -> Path:
        return self._root / f"{run_id}.json"

    def save(self, record: RunRecord) -> None:
        record.artifacts = json_safe(dict(record.artifacts or {})) or {}
        record.result = json_safe(dict(record.result or {})) or {}
        if not isinstance(record.artifacts, dict):
            record.artifacts = {}
        if not isinstance(record.result, dict):
            record.result = {"raw": record.result}
        if is_database_available():
            with session_scope() as session:
                row = session.get(RunRecordORM, record.run_id)
                data = _record_to_orm_data(record)
                if row:
                    for key, value in data.items():
                        setattr(row, key, value)
                else:
                    session.add(RunRecordORM(**data))
            return
        self.path_for(record.run_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def load(self, run_id: str) -> RunRecord | None:
        if is_database_available():
            with session_scope() as session:
                row = session.get(RunRecordORM, run_id)
                return _orm_to_record(row) if row else None
        path = self.path_for(run_id)
        if not path.is_file():
            return None
        return RunRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_runs(self, limit: int = 50) -> list[RunRecord]:
        if is_database_available():
            with session_scope() as session:
                rows = (
                    session.query(RunRecordORM)
                    .order_by(RunRecordORM.started_at.desc(), RunRecordORM.run_id.desc())
                    .limit(limit)
                    .all()
                )
                return [_orm_to_record(row) for row in rows]
        files = sorted(self._root.glob("*.json"), reverse=True)
        records: list[RunRecord] = []
        for path in files[:limit]:
            try:
                records.append(RunRecord.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, ValueError):
                continue
        return records

    def finish(
        self,
        run_id: str,
        status: RunStatus,
        message: str = "",
        result: dict[str, Any] | None = None,
        listing_labels: list[str] | None = None,
    ) -> None:
        record = self.load(run_id)
        if not record:
            return
        if record.status == RunStatus.CANCELED:
            return
        record.status = status
        record.message = _clamp_message(message)
        record.finished_at = datetime.now()
        record.phase = TaskPhase.REPORT
        if result is not None:
            record.result = result
        if listing_labels is not None:
            record.listing_labels = listing_labels
        self.save(record)


def _record_to_orm_data(record: RunRecord) -> dict[str, Any]:
    artifacts = json_safe(dict(record.artifacts or {}))
    result = json_safe(dict(record.result or {}))
    return {
        "run_id": record.run_id,
        "agent": record.agent.value,
        "account_id": record.account_id,
        "status": record.status.value,
        "phase": record.phase.value,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "message": record.message,
        "listing_labels": list(record.listing_labels),
        "artifacts": artifacts if isinstance(artifacts, dict) else {},
        "result": result if isinstance(result, dict) else {"raw": result},
    }


def _orm_to_record(row: RunRecordORM) -> RunRecord:
    return RunRecord(
        run_id=row.run_id,
        agent=AgentKind(row.agent),
        account_id=row.account_id,
        status=RunStatus(row.status),
        phase=TaskPhase(row.phase),
        started_at=row.started_at,
        finished_at=row.finished_at,
        message=row.message or "",
        listing_labels=list(row.listing_labels or []),
        artifacts=dict(row.artifacts or {}),
        result=dict(row.result or {}),
    )

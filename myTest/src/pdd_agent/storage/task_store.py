"""任务运行记录持久化到 data/runs/*.json。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import cast, or_
from sqlalchemy import String as SqlString

from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.models import RunRecordORM
from pdd_agent.db.session import is_database_available, session_scope
from pdd_agent.domain.enums import AgentKind, RunStatus, TaskPhase
from pdd_agent.domain.models import RunRecord

_DB_MESSAGE_MAX = 2000


def _clamp_message(message: str, limit: int = _DB_MESSAGE_MAX) -> str:
    text = str(message or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(共{len(text)}字)"


class TaskRunStore:
    """每次 CLI/API 执行任务时创建 RunRecord，便于审计与失败重跑。"""

    def __init__(self, runs_root: Path | None = None) -> None:
        settings = load_yaml_settings()
        self._root = runs_root or settings.paths.resolve("runs_root")
        if not is_database_available():
            self._root.mkdir(parents=True, exist_ok=True)

    def create_run(self, agent: AgentKind, account_id: str) -> RunRecord:
        """创建新运行记录并立即落盘。"""
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

        path = self.path_for(record.run_id)
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

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
        """按 run_id 倒序返回最近任务（run_id 含时间前缀）。"""
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

    def search_runs(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        account_id: str = "",
        agent: str = "",
        status: str = "",
        started_from: datetime | None = None,
        started_to: datetime | None = None,
        product_code: str = "",
    ) -> tuple[list[RunRecord], int]:
        page = max(1, page)
        page_size = max(1, min(200, page_size))

        if is_database_available():
            with session_scope() as session:
                query = session.query(RunRecordORM)
                if account_id:
                    query = query.filter(RunRecordORM.account_id == account_id)
                if agent:
                    query = query.filter(RunRecordORM.agent == agent)
                if status:
                    query = query.filter(RunRecordORM.status == status)
                if started_from:
                    query = query.filter(RunRecordORM.started_at >= started_from)
                if started_to:
                    query = query.filter(RunRecordORM.started_at <= started_to)
                if product_code:
                    pattern = f"%{product_code}%"
                    query = query.filter(
                        or_(
                            cast(RunRecordORM.listing_labels, SqlString).like(pattern),
                            cast(RunRecordORM.result, SqlString).like(pattern),
                            RunRecordORM.message.like(pattern),
                        )
                    )
                total = int(query.order_by(None).count())
                rows = (
                    query.order_by(RunRecordORM.started_at.desc(), RunRecordORM.run_id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                    .all()
                )
                return [_orm_to_record(row) for row in rows], total

        records = self.list_runs(limit=10_000)
        filtered = [
            r
            for r in records
            if (not account_id or r.account_id == account_id)
            and (not agent or r.agent.value == agent)
            and (not status or r.status.value == status)
            and (not started_from or r.started_at >= started_from)
            and (not started_to or r.started_at <= started_to)
            and (not product_code or _record_contains_product(r, product_code))
        ]
        total = len(filtered)
        start = (page - 1) * page_size
        return filtered[start : start + page_size], total

    def update_phase(self, run_id: str, phase: TaskPhase) -> None:
        record = self.load(run_id)
        if not record:
            return
        record.phase = phase
        self.save(record)

    def update_status(self, run_id: str, status: RunStatus, message: str = "") -> None:
        record = self.load(run_id)
        if not record:
            return
        if record.status == RunStatus.CANCELED:
            return
        record.status = status
        if message:
            record.message = _clamp_message(message)
        self.save(record)

    def finish(
        self,
        run_id: str,
        status: RunStatus,
        message: str = "",
        result: dict[str, Any] | None = None,
        listing_labels: list[str] | None = None,
    ) -> None:
        """标记任务结束并写入终态。"""
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

    def append_listing_result(self, run_id: str, item: dict[str, Any]) -> None:
        """上架过程中追加单个单元结果，便于工作台实时同步。"""
        record = self.load(run_id)
        if not record:
            return
        current = dict(record.result or {})
        results = list(current.get("results") or [])
        results.append(dict(item))
        current["results"] = results
        record.result = current
        label = str(item.get("listing_label") or "").strip()
        if label and label not in record.listing_labels:
            record.listing_labels = list(record.listing_labels) + [label]
        self.save(record)


def _record_to_orm_data(record: RunRecord) -> dict[str, Any]:
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
        "artifacts": dict(record.artifacts),
        "result": dict(record.result),
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


def _record_contains_product(record: RunRecord, product_code: str) -> bool:
    needle = product_code.lower()
    if any(needle in label.lower() for label in record.listing_labels):
        return True
    if needle in (record.message or "").lower():
        return True
    try:
        return needle in json.dumps(record.result, ensure_ascii=False).lower()
    except TypeError:
        return False

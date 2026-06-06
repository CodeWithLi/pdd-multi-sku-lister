"""任务运行记录持久化到 data/runs/*.json。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pdd_agent.core.config import load_yaml_settings
from pdd_agent.domain.enums import AgentKind, RunStatus, TaskPhase
from pdd_agent.domain.models import RunRecord


class TaskRunStore:
    """每次 CLI/API 执行任务时创建 RunRecord，便于审计与失败重跑。"""

    def __init__(self, runs_root: Path | None = None) -> None:
        settings = load_yaml_settings()
        self._root = runs_root or settings.paths.resolve("runs_root")
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
        path = self.path_for(record.run_id)
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def load(self, run_id: str) -> RunRecord | None:
        path = self.path_for(run_id)
        if not path.is_file():
            return None
        return RunRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_runs(self, limit: int = 50) -> list[RunRecord]:
        """按 run_id 倒序返回最近任务（run_id 含时间前缀）。"""
        files = sorted(self._root.glob("*.json"), reverse=True)
        records: list[RunRecord] = []
        for path in files[:limit]:
            try:
                records.append(RunRecord.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, ValueError):
                continue
        return records

    def update_phase(self, run_id: str, phase: TaskPhase) -> None:
        record = self.load(run_id)
        if not record:
            return
        record.phase = phase
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
        record.status = status
        record.message = message
        record.finished_at = datetime.now()
        record.phase = TaskPhase.REPORT
        if result is not None:
            record.result = result
        if listing_labels is not None:
            record.listing_labels = listing_labels
        self.save(record)

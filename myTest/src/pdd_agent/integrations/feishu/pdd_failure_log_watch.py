"""失败日志循环上架候选筛选与轮询检测。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    PddFailureCycleRelistWatchConfig,
    load_feishu_config,
)
from pdd_agent.integrations.feishu.pdd_failure_log_read import list_pdd_failure_logs
from pdd_agent.integrations.feishu.field_display import is_cycle_relist_unselected


@dataclass(frozen=True)
class CycleRelistCandidate:
    record_id: str
    merchant_code: str
    account_name: str
    report_platform: str
    record_type: str
    failure_reason: str
    process_status: str
    cycle_relist: str
    processor: str
    processed_at: str
    date: str

    def to_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "merchant_code": self.merchant_code,
            "account_name": self.account_name,
            "report_platform": self.report_platform,
            "record_type": self.record_type,
            "failure_reason": self.failure_reason,
            "process_status": self.process_status,
            "cycle_relist": self.cycle_relist,
            "processor": self.processor,
            "processed_at": self.processed_at,
            "date": self.date,
        }


def is_cycle_relist_candidate(
    *,
    process_status: str,
    cycle_relist: str,
    failure_reason: str,
    watch: PddFailureCycleRelistWatchConfig,
) -> bool:
    """处理状态已完成 + 循环上架为空 + 失败原因不含排除短语。"""
    status = str(process_status or "").strip()
    completed = {str(x).strip() for x in watch.completed_statuses if str(x).strip()}
    if status not in completed:
        return False
    if not is_cycle_relist_unselected(cycle_relist):
        return False
    exclude = str(watch.exclude_failure_reason_contains or "").strip()
    if exclude and exclude in str(failure_reason or ""):
        return False
    return True


def _item_to_candidate(item: dict[str, Any]) -> CycleRelistCandidate:
    process = item.get("process_completed") or {}
    return CycleRelistCandidate(
        record_id=str(item.get("record_id") or ""),
        merchant_code=str(item.get("merchant_code") or ""),
        account_name=str(item.get("account_name") or ""),
        report_platform=str(item.get("report_platform") or ""),
        record_type=str(item.get("record_type") or ""),
        failure_reason=str(item.get("failure_reason") or ""),
        process_status=str(process.get("label") or ""),
        cycle_relist=str(item.get("cycle_relist") or ""),
        processor=str(item.get("processor") or ""),
        processed_at=str(item.get("processed_at") or ""),
        date=str(item.get("date") or ""),
    )


def list_cycle_relist_candidates(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    *,
    watch: PddFailureCycleRelistWatchConfig | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    watch_cfg = watch or cfg.pdd_upload_log.failure_cycle_relist_watch
    limit = max(1, min(int(watch_cfg.fetch_limit), 500))

    payload = list_pdd_failure_logs(cfg, client, limit=limit)
    if not payload.get("ok"):
        return {
            "ok": False,
            "error": str(payload.get("error") or "读取失败日志失败"),
            "items": [],
            "total": 0,
        }

    candidates: list[CycleRelistCandidate] = []
    for row in payload.get("items") or []:
        candidate = _item_to_candidate(row)
        if is_cycle_relist_candidate(
            process_status=candidate.process_status,
            cycle_relist=candidate.cycle_relist,
            failure_reason=candidate.failure_reason,
            watch=watch_cfg,
        ):
            candidates.append(candidate)

    return {
        "ok": True,
        "total": len(candidates),
        "items": [c.to_dict() for c in candidates],
        "watch": watch_cfg.model_dump(),
        "table_id": str(payload.get("table_id") or ""),
        "table_name": str(payload.get("table_name") or ""),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

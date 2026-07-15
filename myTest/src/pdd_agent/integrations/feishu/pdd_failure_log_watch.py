"""失败日志循环上架候选筛选与轮询检测。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import iter_search_record_pages, list_all_records
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    PddFailureCycleRelistWatchConfig,
    load_feishu_config,
)
from pdd_agent.integrations.feishu.pdd_failure_log_read import (
    build_cycle_relist_candidate_search_filter,
    parse_failure_log_record,
    resolve_failure_log_table_context,
)
from pdd_agent.integrations.feishu.field_display import is_cycle_relist_unselected

logger = get_logger(__name__)
_INVALID_FILTER_CODES = frozenset({1254018})


@dataclass(frozen=True)
class CycleRelistCandidate:
    record_id: str
    merchant_code: str
    account_name: str
    account_id: str
    report_platform: str
    record_type: str
    failure_reason: str
    process_status: str
    cycle_relist: str
    processor: str
    processed_at: str
    date: str
    system_reason: str = ""
    source_pipeline_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "merchant_code": self.merchant_code,
            "account_name": self.account_name,
            "account_id": self.account_id,
            "report_platform": self.report_platform,
            "record_type": self.record_type,
            "failure_reason": self.failure_reason,
            "process_status": self.process_status,
            "cycle_relist": self.cycle_relist,
            "processor": self.processor,
            "processed_at": self.processed_at,
            "date": self.date,
            "system_reason": self.system_reason,
            "source_pipeline_id": self.source_pipeline_id,
        }


def is_cycle_relist_candidate(
    *,
    process_status: str,
    cycle_relist: str,
    failure_reason: str,
    watch: PddFailureCycleRelistWatchConfig,
    record_date: str = "",
) -> bool:
    """处理状态已完成 + 循环上架为空 + 失败原因不含排除短语 + 可选日期筛选。"""
    from pdd_agent.integrations.feishu.failure_cycle_relist_exclude import (
        failure_reason_matches_exclude_phrases,
    )
    from pdd_agent.integrations.feishu.failure_cycle_relist_date_filter import (
        record_date_meets_fetch_after,
    )

    status = str(process_status or "").strip()
    completed = {str(x).strip() for x in watch.completed_statuses if str(x).strip()}
    if status not in completed:
        return False
    if not is_cycle_relist_unselected(cycle_relist):
        return False
    if failure_reason_matches_exclude_phrases(
        failure_reason,
        watch.exclude_failure_reason_contains,
    ):
        return False
    if not record_date_meets_fetch_after(
        record_date=record_date,
        fetch_after_date=getattr(watch, "fetch_after_date", "") or "",
    ):
        return False
    return True


def _item_to_candidate(item: dict[str, Any]) -> CycleRelistCandidate:
    from pdd_agent.integrations.feishu.failure_log_pipeline_system_reason import (
        enrich_failure_log_item_source_pipeline_id,
    )

    row = dict(item or {})
    process = row.get("process_completed") or {}
    enrich_failure_log_item_source_pipeline_id(row)
    return CycleRelistCandidate(
        record_id=str(row.get("record_id") or ""),
        merchant_code=str(row.get("merchant_code") or ""),
        account_name=str(row.get("account_name") or ""),
        account_id=str(row.get("account_id") or ""),
        report_platform=str(row.get("report_platform") or ""),
        record_type=str(row.get("record_type") or ""),
        failure_reason=str(row.get("failure_reason") or ""),
        process_status=str(process.get("label") or ""),
        cycle_relist=str(row.get("cycle_relist") or ""),
        processor=str(row.get("processor") or ""),
        processed_at=str(row.get("processed_at") or ""),
        date=str(row.get("date") or ""),
        system_reason=str(row.get("system_reason") or ""),
        source_pipeline_id=str(row.get("source_pipeline_id") or ""),
    )


def _completed_statuses(watch: PddFailureCycleRelistWatchConfig) -> list[str]:
    statuses = [str(x).strip() for x in watch.completed_statuses if str(x).strip()]
    return statuses or ["已结束", "已处理完成"]


def _rows_to_candidates(
    rows: list[dict[str, Any]],
    *,
    watch: PddFailureCycleRelistWatchConfig,
    max_candidates: int,
) -> list[CycleRelistCandidate]:
    candidates: list[CycleRelistCandidate] = []
    seen: set[str] = set()
    for row in rows:
        candidate = _item_to_candidate(row)
        rid = candidate.record_id
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        if not is_cycle_relist_candidate(
            process_status=candidate.process_status,
            cycle_relist=candidate.cycle_relist,
            failure_reason=candidate.failure_reason,
            watch=watch,
            record_date=candidate.date,
        ):
            continue
        candidates.append(candidate)
        if len(candidates) >= max_candidates:
            break
    return candidates


def _collect_cycle_relist_rows_via_search(
    ctx,
    api: FeishuClient,
    *,
    watch: PddFailureCycleRelistWatchConfig,
    page_size: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for status in _completed_statuses(watch):
        filter_body = build_cycle_relist_candidate_search_filter(
            ctx,
            api,
            completed_status=status,
            fetch_after_date=str(getattr(watch, "fetch_after_date", "") or ""),
        )
        for batch in iter_search_record_pages(
            api,
            ctx.app_token,
            ctx.table_id,
            filter_body=filter_body,
            page_size=page_size,
        ):
            for record in batch:
                rid = str(record.get("record_id") or record.get("id") or "").strip()
                if rid and rid in seen_ids:
                    continue
                if rid:
                    seen_ids.add(rid)
                rows.append(parse_failure_log_record(record, ctx))
    return rows


def _collect_cycle_relist_rows_via_list_all(
    ctx,
    api: FeishuClient,
    *,
    watch: PddFailureCycleRelistWatchConfig,
    page_size: int,
    max_candidates: int,
) -> list[dict[str, Any]]:
    max_scan = max(max_candidates * 5, page_size * 3, 200)
    raw_records = list_all_records(api, ctx.app_token, ctx.table_id, page_size=page_size)
    if len(raw_records) > max_scan:
        raw_records = raw_records[:max_scan]
    return [parse_failure_log_record(record, ctx) for record in raw_records]


def list_cycle_relist_candidates(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    *,
    watch: PddFailureCycleRelistWatchConfig | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    api = client or FeishuClient(cfg)
    watch_cfg = watch or cfg.pdd_upload_log.failure_cycle_relist_watch
    max_candidates = max(1, min(int(watch_cfg.fetch_limit), 500))
    page_size = max(1, min(int(watch_cfg.fetch_page_size or 50), 200))

    resolved = resolve_failure_log_table_context(cfg, api)
    if isinstance(resolved, dict):
        return {
            "ok": False,
            "error": str(resolved.get("error") or "读取失败日志失败"),
            "items": [],
            "total": 0,
        }
    ctx = resolved

    rows: list[dict[str, Any]] = []
    fetch_mode = "search"
    try:
        rows = _collect_cycle_relist_rows_via_search(
            ctx,
            api,
            watch=watch_cfg,
            page_size=page_size,
        )
    except FeishuAPIError as exc:
        if exc.code not in _INVALID_FILTER_CODES:
            raise
        fetch_mode = "list_all_fallback"
        logger.warning(
            "cycle relist feishu search filter invalid (code=%s), fallback to paginated list_all: %s",
            exc.code,
            exc,
        )
        rows = _collect_cycle_relist_rows_via_list_all(
            ctx,
            api,
            watch=watch_cfg,
            page_size=page_size,
            max_candidates=max_candidates,
        )

    candidates = _rows_to_candidates(rows, watch=watch_cfg, max_candidates=max_candidates)

    return {
        "ok": True,
        "total": len(candidates),
        "items": [c.to_dict() for c in candidates],
        "watch": watch_cfg.model_dump(),
        "table_id": ctx.table_id,
        "table_name": ctx.table_name,
        "fetch_page_size": page_size,
        "fetch_mode": fetch_mode,
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

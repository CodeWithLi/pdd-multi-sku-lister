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
    """处理状态已完成 + 循环上架为空/否 + 失败原因不含排除短语 + 可选日期筛选。"""
    return cycle_relist_reject_reason(
        process_status=process_status,
        cycle_relist=cycle_relist,
        failure_reason=failure_reason,
        watch=watch,
        record_date=record_date,
    ) is None


def cycle_relist_reject_reason(
    *,
    process_status: str,
    cycle_relist: str,
    failure_reason: str,
    watch: PddFailureCycleRelistWatchConfig,
    record_date: str = "",
) -> str | None:
    """返回未入选原因；通过则 None。"""
    from pdd_agent.integrations.feishu.failure_cycle_relist_exclude import (
        failure_reason_matches_exclude_phrases,
    )
    from pdd_agent.integrations.feishu.failure_cycle_relist_date_filter import (
        record_date_meets_fetch_after,
    )

    status = str(process_status or "").strip()
    completed = {str(x).strip() for x in watch.completed_statuses if str(x).strip()}
    if status not in completed:
        return f"process_status={status!r}"
    if not is_cycle_relist_unselected(cycle_relist):
        return f"cycle_relist={str(cycle_relist or '')!r}"
    if failure_reason_matches_exclude_phrases(
        failure_reason,
        watch.exclude_failure_reason_contains,
    ):
        return "exclude_failure_reason"
    if not record_date_meets_fetch_after(
        record_date=record_date,
        fetch_after_date=getattr(watch, "fetch_after_date", "") or "",
    ):
        return f"date={str(record_date or '')!r}<fetch_after={getattr(watch, 'fetch_after_date', '')!r}"
    return None


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
    from pdd_agent.integrations.feishu.failure_cycle_relist_date_filter import (
        parse_failure_log_date,
        record_date_meets_fetch_after,
    )

    fetch_after = str(getattr(watch, "fetch_after_date", "") or "")
    fetch_after_day = parse_failure_log_date(fetch_after)
    date_field = str(getattr(ctx.names, "date", "") or "日期").strip() or "日期"
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for status in _completed_statuses(watch):
        filter_body = build_cycle_relist_candidate_search_filter(
            ctx,
            api,
            completed_status=status,
            fetch_after_date=fetch_after,
        )
        for batch in iter_search_record_pages(
            api,
            ctx.app_token,
            ctx.table_id,
            filter_body=filter_body,
            page_size=page_size,
            sort=[{"field_name": date_field, "desc": True}],
        ):
            crossed_fetch_after = False
            for record in batch:
                rid = str(record.get("record_id") or record.get("id") or "").strip()
                if rid and rid in seen_ids:
                    continue
                if rid:
                    seen_ids.add(rid)
                parsed = parse_failure_log_record(record, ctx)
                record_day = parse_failure_log_date(parsed.get("date") or "")
                if fetch_after_day is not None and record_day is not None and record_day < fetch_after_day:
                    crossed_fetch_after = True
                    continue
                if not record_date_meets_fetch_after(
                    record_date=parsed.get("date") or "",
                    fetch_after_date=fetch_after,
                ):
                    continue
                rows.append(parsed)
            if crossed_fetch_after:
                break
    rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return rows


def _collect_cycle_relist_rows_via_list_all(
    ctx,
    api: FeishuClient,
    *,
    watch: PddFailureCycleRelistWatchConfig,
    page_size: int,
    max_candidates: int,
) -> list[dict[str, Any]]:
    """全表回退：扫完整表，按抓取时间先丢掉旧行，避免只拿表头几百条漏掉表尾新记录。"""
    from pdd_agent.integrations.feishu.failure_cycle_relist_date_filter import (
        record_date_meets_fetch_after,
    )

    fetch_after = str(getattr(watch, "fetch_after_date", "") or "")
    # 有日期筛选时必须扫全表；无筛选时仍限制扫描量防拖垮
    max_scan = 0 if fetch_after else max(max_candidates * 20, page_size * 10, 1000)
    raw_records = list_all_records(api, ctx.app_token, ctx.table_id, page_size=page_size)
    if max_scan > 0 and len(raw_records) > max_scan:
        # 无日期筛选：优先取表尾（通常更新记录在后面），再倒序拼接头尾
        head = raw_records[: max_scan // 2]
        tail = raw_records[-(max_scan - len(head)) :]
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for record in list(reversed(tail)) + head:
            rid = str(record.get("record_id") or record.get("id") or "").strip()
            if rid and rid in seen:
                continue
            if rid:
                seen.add(rid)
            merged.append(record)
        raw_records = merged

    rows: list[dict[str, Any]] = []
    for record in raw_records:
        parsed = parse_failure_log_record(record, ctx)
        if not record_date_meets_fetch_after(
            record_date=parsed.get("date") or "",
            fetch_after_date=fetch_after,
        ):
            continue
        rows.append(parsed)
    # 日期新→旧，优先凑满候选
    rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return rows


def _log_candidate_filter_diagnostics(
    rows: list[dict[str, Any]],
    *,
    watch: PddFailureCycleRelistWatchConfig,
    candidates: list[CycleRelistCandidate],
) -> None:
    """候选为 0 或命中调试编码时，打印筛掉原因。"""
    fetch_after = str(getattr(watch, "fetch_after_date", "") or "")
    reason_counts: dict[str, int] = {}
    interesting: list[str] = []
    for row in rows:
        cand = _item_to_candidate(row)
        reason = cycle_relist_reject_reason(
            process_status=cand.process_status,
            cycle_relist=cand.cycle_relist,
            failure_reason=cand.failure_reason,
            watch=watch,
            record_date=cand.date,
        )
        key = reason or "ok"
        # 聚合：日期类合并前缀，避免爆炸
        if key.startswith("date="):
            bucket = "date_mismatch"
        elif key.startswith("process_status="):
            bucket = "process_status"
        elif key.startswith("cycle_relist="):
            bucket = f"cycle_relist:{cand.cycle_relist or '∅'}"
        else:
            bucket = key
        reason_counts[bucket] = reason_counts.get(bucket, 0) + 1
        code = str(cand.merchant_code or "").strip().upper()
        if code == "BD103A" or (reason is None and len(interesting) < 5):
            interesting.append(
                f"{cand.merchant_code}|{cand.account_name}|date={cand.date}|"
                f"status={cand.process_status}|cycle={cand.cycle_relist!r}|"
                f"pipeline={cand.source_pipeline_id or '-'}|reject={reason or 'ok'}"
            )

    logger.info(
        "cycle relist filter diagnostics fetch_after=%s raw=%s candidates=%s reject_buckets=%s samples=%s",
        fetch_after or "(none)",
        len(rows),
        len(candidates),
        reason_counts,
        interesting[:8],
    )


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
    fetch_after = str(getattr(watch_cfg, "fetch_after_date", "") or "")

    logger.info(
        "cycle relist fetch begin table_scan fetch_after=%s completed=%s limit=%s page_size=%s exclude=%s",
        fetch_after or "(none)",
        list(_completed_statuses(watch_cfg)),
        max_candidates,
        page_size,
        list(watch_cfg.exclude_failure_reason_contains or [])[:3],
    )

    resolved = resolve_failure_log_table_context(cfg, api)
    if isinstance(resolved, dict):
        logger.warning(
            "cycle relist fetch resolve table failed: %s",
            resolved.get("error") or resolved,
        )
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
    logger.info(
        "cycle relist fetch done mode=%s table=%s raw_rows=%s candidates=%s codes=%s",
        fetch_mode,
        ctx.table_name or ctx.table_id,
        len(rows),
        len(candidates),
        [c.merchant_code for c in candidates[:8]],
    )
    if not candidates or any(
        str(c.merchant_code or "").strip().upper() == "BD103A" for c in candidates
    ) or any(str(r.get("merchant_code") or "").strip().upper() == "BD103A" for r in rows):
        _log_candidate_filter_diagnostics(rows, watch=watch_cfg, candidates=candidates)
    elif rows:
        # 有拉取行但筛空：始终打诊断
        _log_candidate_filter_diagnostics(rows, watch=watch_cfg, candidates=candidates)

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

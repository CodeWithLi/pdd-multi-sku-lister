"""
整合链路 — 分批上架「批内断点续跑」。

目标：当前批 success + failed + pending == 批大小（如 10），重启后只跑失败/未跑，已成功不重复。
可单独启用/禁用；业务入口仅调用 prepare / merge / persist 三个薄封装。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, update_integrated_pipeline
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)

META_BATCH_PROGRESS_KEY = "batch_progress"


class BatchUnitOutcome(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class BatchUnitSlot:
    selector: str
    listing_label: str
    outcome: BatchUnitOutcome
    result_item: dict[str, Any] | None = None


@dataclass
class BatchResumePlan:
    """当前批续跑计划。"""

    pipeline_id: str
    batch_index: int
    batch_size: int
    total_batches: int = 0
    batch_selectors: list[str] = field(default_factory=list)
    success: list[BatchUnitSlot] = field(default_factory=list)
    failed: list[BatchUnitSlot] = field(default_factory=list)
    pending: list[BatchUnitSlot] = field(default_factory=list)
    skipped: list[BatchUnitSlot] = field(default_factory=list)
    to_run_selectors: list[str] = field(default_factory=list)
    prior_result_items: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "batch_index": self.batch_index,
            "batch_size": self.batch_size,
            "success": len(self.success),
            "failed": len(self.failed),
            "pending": len(self.pending),
            "skipped": len(self.skipped),
            "to_run": len(self.to_run_selectors),
        }


def selector_to_listing_label(selector: str) -> str:
    from pdd_agent.api.services.pipeline_service import _selector_to_listing_label

    return _selector_to_listing_label(selector)


def compact_unit_result_item(item: dict[str, Any]) -> dict[str, Any]:
    label = str(item.get("listing_label") or "").strip()
    return {
        "listing_label": label,
        "status": item.get("status"),
        "pdd_product_id": item.get("pdd_product_id"),
        "reason": item.get("reason") or item.get("reason_code"),
        "error": item.get("error"),
        "selector": item.get("selector"),
    }


def classify_listing_unit_outcome(item: dict[str, Any] | None) -> BatchUnitOutcome:
    if not item or not isinstance(item, dict):
        return BatchUnitOutcome.PENDING
    status = str(item.get("status") or "").strip().lower()
    reason = str(item.get("reason") or item.get("reason_code") or "").strip().lower()
    product_id = str(item.get("pdd_product_id") or "").strip()
    if status in {"success", "listed"} and (product_id or status == "listed"):
        return BatchUnitOutcome.SUCCESS
    if status == "skipped" or reason in {
        "platform_skip_dedupe",
        "platform_not_applicable",
        "skipped_already_listed",
    }:
        return BatchUnitOutcome.SKIPPED
    if status in {"failed", "retryable"} or reason:
        return BatchUnitOutcome.FAILED
    return BatchUnitOutcome.PENDING


def _label_to_selector(batch_selectors: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for selector in batch_selectors:
        text = str(selector or "").strip()
        if not text:
            continue
        mapping[selector_to_listing_label(text)] = text
    return mapping


def _load_results_by_label_from_run(run_id: str) -> dict[str, dict[str, Any]]:
    if not run_id:
        return {}
    record = TaskRunStore().load(run_id)
    if not record:
        return {}
    result = dict(record.result or {})
    out: dict[str, dict[str, Any]] = {}
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("listing_label") or "").strip()
        if label:
            out[label] = dict(item)
    return out


def _load_batch_progress_map(throttle: dict[str, Any], batch_index: int) -> dict[str, dict[str, Any]]:
    progress = dict(throttle.get(META_BATCH_PROGRESS_KEY) or {})
    batch_bucket = dict(progress.get(str(batch_index)) or {})
    raw = dict(batch_bucket.get("unit_results_by_label") or {})
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def _load_global_unit_results_for_labels(
    throttle: dict[str, Any],
    labels: set[str],
) -> dict[str, dict[str, Any]]:
    accumulated = dict(throttle.get("unit_results_by_label") or {})
    out: dict[str, dict[str, Any]] = {}
    for label in labels:
        item = accumulated.get(label)
        if isinstance(item, dict):
            out[label] = dict(item)
    return out


def _merge_result_sources(*sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        for label, item in source.items():
            if label and isinstance(item, dict):
                merged[label] = dict(item)
    return merged


def _current_batch_selectors(throttle: dict[str, Any]) -> tuple[int, list[str]]:
    batches = list(throttle.get("batches") or [])
    batch_index = int(throttle.get("batch_index") or 0)
    if not batches:
        return batch_index, []
    if batch_index < 0 or batch_index >= len(batches):
        batch_index = 0
    return batch_index, [str(s).strip() for s in batches[batch_index] if str(s).strip()]


def build_batch_resume_plan(
    *,
    pipeline_id: str,
    run_id: str,
    requested_codes: list[str],
) -> BatchResumePlan | None:
    """
    根据整合链路 meta + 当前 run 已有结果，生成批内续跑计划。
    非分批链路返回 None。
    """
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id:
        return None

    row = get_integrated_pipeline(pipeline_id)
    if not row:
        return None

    throttle = dict((row.meta or {}).get("listing_throttle") or {})
    if not throttle.get("enabled"):
        return None

    batch_index, batch_selectors = _current_batch_selectors(throttle)
    if not batch_selectors:
        return None

    label_to_selector = _label_to_selector(batch_selectors)
    labels = set(label_to_selector)

    run_results = _load_results_by_label_from_run(run_id)
    batch_progress = _load_batch_progress_map(throttle, batch_index)
    global_results = _load_global_unit_results_for_labels(throttle, labels)
    # run 结果优先，其次批进度，再次全局累计
    merged = _merge_result_sources(global_results, batch_progress, run_results)

    plan = BatchResumePlan(
        pipeline_id=pipeline_id,
        batch_index=batch_index,
        batch_size=len(batch_selectors),
        total_batches=int(throttle.get("total_batches") or 0),
        batch_selectors=list(batch_selectors),
    )

    for selector in batch_selectors:
        label = selector_to_listing_label(selector)
        item = merged.get(label)
        outcome = classify_listing_unit_outcome(item)
        slot = BatchUnitSlot(
            selector=selector,
            listing_label=label,
            outcome=outcome,
            result_item=dict(item) if item else None,
        )
        if outcome == BatchUnitOutcome.SUCCESS:
            plan.success.append(slot)
            if item:
                plan.prior_result_items.append(dict(item))
        elif outcome == BatchUnitOutcome.SKIPPED:
            plan.skipped.append(slot)
            if item:
                plan.prior_result_items.append(dict(item))
        elif outcome == BatchUnitOutcome.FAILED:
            plan.failed.append(slot)
        else:
            plan.pending.append(slot)

    requested_set = {str(c).strip() for c in requested_codes if str(c).strip()}
    canonical_set = set(batch_selectors)
    if requested_set and requested_set != canonical_set:
        logger.warning(
            "batch resume pipeline=%s batch=%s payload selectors mismatch: payload=%s canonical=%s",
            pipeline_id,
            batch_index + 1,
            len(requested_set),
            len(canonical_set),
        )

    to_run: list[str] = []
    for slot in (*plan.failed, *plan.pending):
        if slot.selector not in to_run:
            to_run.append(slot.selector)
    plan.to_run_selectors = to_run

    total_accounted = (
        len(plan.success) + len(plan.failed) + len(plan.pending) + len(plan.skipped)
    )
    if total_accounted != plan.batch_size:
        logger.warning(
            "batch resume pipeline=%s batch=%s slot count mismatch: accounted=%s batch_size=%s",
            pipeline_id,
            batch_index + 1,
            total_accounted,
            plan.batch_size,
        )

    return plan


def prepare_listing_batch_resume(
    *,
    pipeline_id: str,
    run_id: str,
    product_codes: list[str],
) -> tuple[list[str], BatchResumePlan | None]:
    """
    执行 listing 前调用：返回 (应执行的 selectors, 续跑计划)。
    无续跑时原样返回 product_codes。
    """
    plan = build_batch_resume_plan(
        pipeline_id=pipeline_id,
        run_id=run_id,
        requested_codes=list(product_codes or []),
    )
    if not plan:
        return list(product_codes or []), None

    summary = plan.summary()
    logger.info(
        "batch resume pipeline=%s batch=%s/%s size=%s success=%s failed=%s pending=%s skipped=%s to_run=%s",
        plan.pipeline_id,
        plan.batch_index + 1,
        plan.total_batches or "?",
        plan.batch_size,
        summary["success"],
        summary["failed"],
        summary["pending"],
        summary["skipped"],
        summary["to_run"],
    )

    if not plan.to_run_selectors:
        return [], plan
    return list(plan.to_run_selectors), plan


def merge_resumed_listing_graph_result(
    plan: BatchResumePlan | None,
    graph_result: dict[str, Any],
) -> dict[str, Any]:
    """graph 返回后合并：保留本批已成功/跳过项，叠加本次新结果。"""
    if not plan:
        return graph_result

    merged = dict(graph_result or {})
    new_items = [
        dict(item)
        for item in (merged.get("results") or [])
        if isinstance(item, dict)
    ]
    combined = merge_listing_result_items(plan.prior_result_items, new_items)
    merged["results"] = combined
    merged["batch_resume"] = plan.summary()
    return merged


def merge_listing_result_items(
    prior_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按 listing_label 合并；新结果覆盖同 label 旧结果（失败重试）。"""
    by_label: dict[str, dict[str, Any]] = {}
    for item in prior_items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("listing_label") or "").strip()
        if label:
            by_label[label] = dict(item)
    for item in new_items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("listing_label") or "").strip()
        if label:
            by_label[label] = dict(item)
    return list(by_label.values())


def finish_listing_if_batch_already_complete(
    *,
    run_id: str,
    account_id: str,
    plan: BatchResumePlan,
) -> dict[str, Any] | None:
    """本批已全部成功/跳过时直接收尾，不再开浏览器。"""
    if plan.to_run_selectors:
        return None

    from pdd_agent.api.services.task_runner import (
        _compact_run_result_for_storage,
        _schedule_feishu_listing_result_log,
        _summarize_listing_message,
        mark_feishu_terminal_logged,
    )
    from pdd_agent.domain.enums import RunStatus

    result = {
        "results": merge_listing_result_items(plan.prior_result_items, []),
        "batch_resume": {**plan.summary(), "skipped_run": True},
    }
    store = TaskRunStore()
    labels = [
        str(item.get("listing_label") or "")
        for item in result["results"]
        if str(item.get("listing_label") or "").strip()
    ]
    _schedule_feishu_listing_result_log(
        account_id=account_id,
        run_id=run_id,
        result=result,
        product_codes=plan.batch_selectors,
    )
    store.finish(
        run_id,
        RunStatus.SUCCESS,
        _summarize_listing_message(result),
        result=_compact_run_result_for_storage(result),
        listing_labels=labels,
    )
    mark_feishu_terminal_logged(run_id)
    logger.info(
        "batch resume pipeline=%s batch=%s already complete, skip browser run_id=%s",
        plan.pipeline_id,
        plan.batch_index + 1,
        run_id,
    )
    return result


def persist_batch_unit_outcome_for_run(run_id: str, item: dict[str, Any]) -> None:
    """
    单套上架落库后调用：写入当前批 batch_progress，供重启续跑。
    找不到 pipeline 时静默跳过。
    """
    run_id = str(run_id or "").strip()
    if not run_id or not isinstance(item, dict):
        return

    from pdd_agent.db.repositories import get_integrated_pipeline_by_listing_run_id

    row = get_integrated_pipeline_by_listing_run_id(run_id)
    if not row:
        return

    throttle = dict((row.meta or {}).get("listing_throttle") or {})
    if not throttle.get("enabled"):
        return

    batch_index, batch_selectors = _current_batch_selectors(throttle)
    label = str(item.get("listing_label") or "").strip()
    if not label:
        return

    batch_labels = {selector_to_listing_label(s) for s in batch_selectors}
    if label not in batch_labels:
        return

    compact = compact_unit_result_item(item)
    progress = dict(throttle.get(META_BATCH_PROGRESS_KEY) or {})
    bucket = dict(progress.get(str(batch_index)) or {})
    unit_map = dict(bucket.get("unit_results_by_label") or {})
    unit_map[label] = compact
    bucket["unit_results_by_label"] = unit_map
    progress[str(batch_index)] = bucket

    from pdd_agent.api.services.pipeline_listing_throttle import merge_unit_results_into_throttle

    throttle_patch = merge_unit_results_into_throttle(throttle, {"results": [item]})
    throttle_patch[META_BATCH_PROGRESS_KEY] = progress

    update_integrated_pipeline(
        row.pipeline_id,
        meta_patch={"listing_throttle": throttle_patch},
    )

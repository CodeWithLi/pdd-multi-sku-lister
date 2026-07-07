"""补跑 listing 的断点续跑策略。

目标：
1. 项目重启后，队列恢复补跑任务时，不再重复执行已成功的 selector；
2. 仅封装补跑恢复逻辑，主流程通过薄引用接入；
3. 数据来源优先使用 MySQL 中已持久化的 pipeline meta 与 RunRecord.result。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)


@dataclass
class LateRetryResumePlan:
    pipeline_id: str
    run_id: str
    requested_selectors: list[str] = field(default_factory=list)
    succeeded_selectors: list[str] = field(default_factory=list)
    to_run_selectors: list[str] = field(default_factory=list)
    prior_success_result_items: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "requested": len(self.requested_selectors),
            "already_succeeded": len(self.succeeded_selectors),
            "to_run": len(self.to_run_selectors),
        }


def _norm_selectors(selectors: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in (selectors or []) if str(item).strip()))


def _selector_to_label(selector: str) -> str:
    from pdd_agent.api.services.pipeline_service import _selector_to_listing_label

    return str(_selector_to_listing_label(selector) or "").strip()


def _is_success_item(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").strip().lower()
    product_id = str(item.get("pdd_product_id") or "").strip()
    return status in {"success", "listed"} and (bool(product_id) or status == "listed")


def _load_run_result_items(run_id: str) -> list[dict[str, Any]]:
    record = TaskRunStore().load(str(run_id or "").strip())
    if not record or not isinstance(record.result, dict):
        return []
    return [dict(item) for item in (record.result.get("results") or []) if isinstance(item, dict)]


def build_late_retry_resume_plan(
    *,
    pipeline_id: str,
    run_id: str,
    requested_selectors: list[str],
) -> LateRetryResumePlan | None:
    selectors = _norm_selectors(requested_selectors)
    if not pipeline_id or not run_id or not selectors:
        return None

    row = get_integrated_pipeline(str(pipeline_id or "").strip())
    if not row:
        return None

    from pdd_agent.api.services.pipeline_late_retry_policy import late_retry_state

    state = late_retry_state(row)
    if not state:
        return None

    succeeded_by_state = set(_norm_selectors(list(state.get("succeeded_selectors") or [])))
    prior_success_items = [item for item in _load_run_result_items(run_id) if _is_success_item(item)]
    succeeded_by_run: set[str] = set()
    success_items_by_label: dict[str, dict[str, Any]] = {}
    for item in prior_success_items:
        label = str(item.get("listing_label") or "").strip()
        if not label:
            continue
        success_items_by_label[label] = dict(item)

    for selector in selectors:
        if _selector_to_label(selector) in success_items_by_label:
            succeeded_by_run.add(selector)

    already_succeeded = _norm_selectors([*succeeded_by_state, *succeeded_by_run])
    succeeded_set = set(already_succeeded)
    to_run = [selector for selector in selectors if selector not in succeeded_set]
    kept_prior_items = [
        success_items_by_label[label]
        for label in [_selector_to_label(selector) for selector in selectors]
        if label in success_items_by_label
    ]

    if to_run == selectors and not kept_prior_items:
        return None

    return LateRetryResumePlan(
        pipeline_id=str(pipeline_id or "").strip(),
        run_id=str(run_id or "").strip(),
        requested_selectors=selectors,
        succeeded_selectors=already_succeeded,
        to_run_selectors=to_run,
        prior_success_result_items=kept_prior_items,
    )


def prepare_late_retry_resume(
    *,
    pipeline_id: str,
    run_id: str,
    product_codes: list[str],
) -> tuple[list[str], LateRetryResumePlan | None]:
    plan = build_late_retry_resume_plan(
        pipeline_id=pipeline_id,
        run_id=run_id,
        requested_selectors=list(product_codes or []),
    )
    if not plan:
        return list(product_codes or []), None

    logger.info(
        "late retry resume pipeline=%s run_id=%s requested=%s already_succeeded=%s to_run=%s",
        plan.pipeline_id,
        plan.run_id,
        len(plan.requested_selectors),
        len(plan.succeeded_selectors),
        len(plan.to_run_selectors),
    )
    return list(plan.to_run_selectors), plan


def merge_resumed_late_retry_result(
    plan: LateRetryResumePlan | None,
    graph_result: dict[str, Any],
) -> dict[str, Any]:
    if not plan:
        return graph_result

    merged = dict(graph_result or {})
    new_items = [dict(item) for item in (merged.get("results") or []) if isinstance(item, dict)]
    by_label: dict[str, dict[str, Any]] = {}
    for item in plan.prior_success_result_items:
        label = str(item.get("listing_label") or "").strip()
        if label:
            by_label[label] = dict(item)
    for item in new_items:
        label = str(item.get("listing_label") or "").strip()
        if label:
            by_label[label] = dict(item)
    merged["results"] = list(by_label.values())
    merged["late_retry_resume"] = {**plan.summary(), "skipped_run": not bool(plan.to_run_selectors)}
    return merged


def finish_late_retry_if_already_complete(
    *,
    run_id: str,
    account_id: str,
    plan: LateRetryResumePlan,
) -> dict[str, Any] | None:
    if not plan or plan.to_run_selectors:
        return None

    from pdd_agent.api.services.pipeline_listing_unit_results import listing_result_item_labels
    from pdd_agent.api.services.task_runner import (
        _compact_run_result_for_storage,
        _schedule_feishu_listing_result_log,
        _summarize_listing_message,
        mark_feishu_terminal_logged,
    )
    from pdd_agent.domain.enums import RunStatus

    result = {
        "results": list(plan.prior_success_result_items),
        "late_retry_resume": {**plan.summary(), "skipped_run": True},
    }
    TaskRunStore().finish(
        run_id,
        RunStatus.SUCCESS,
        _summarize_listing_message(result),
        result=_compact_run_result_for_storage(result),
        listing_labels=listing_result_item_labels(result.get("results") or []),
    )
    _schedule_feishu_listing_result_log(
        account_id=account_id,
        run_id=run_id,
        result=result,
        product_codes=plan.requested_selectors,
    )
    mark_feishu_terminal_logged(run_id)
    logger.info(
        "late retry resume skipped browser pipeline=%s run_id=%s already_succeeded=%s",
        plan.pipeline_id,
        run_id,
        len(plan.succeeded_selectors),
    )
    return result

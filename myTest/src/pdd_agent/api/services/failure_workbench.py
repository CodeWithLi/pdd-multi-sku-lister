"""Failure workbench service."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from pdd_agent.api.services.task_queue import enqueue_listing_task
from pdd_agent.api.services.task_runner import create_listing_run
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.repositories import (
    get_failure_item,
    search_failure_items,
    update_failure_decision,
    upsert_failure_item,
)
from pdd_agent.db.session import is_database_available
from pdd_agent.domain.enums import AgentKind, RunStatus
from pdd_agent.storage import TaskRunStore

FAILURE_STATUSES = {"failed", "retryable", "submit_uncertain", "skipped"}


@dataclass
class FailureCandidate:
    item_id: str
    source_run_id: str
    account_id: str
    listing_label: str
    product_code: str
    image_set: str
    merchant_code: str
    item_status: str
    reason: str
    error: str
    retryable: bool
    started_at: datetime | None = None


def make_failure_item_id(source_run_id: str, listing_label: str, product_code: str, image_set: str) -> str:
    raw = "|".join([source_run_id, listing_label, product_code, image_set])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def extract_failure_candidates(limit_runs: int = 1000) -> list[FailureCandidate]:
    store = TaskRunStore()
    records = store.list_runs(limit=limit_runs)
    candidates: list[FailureCandidate] = []
    for record in records:
        if record.agent != AgentKind.LISTING:
            continue
        results = record.result.get("results")
        if not isinstance(results, list):
            continue
        for item in results:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "")
            retryable = bool(item.get("retryable"))
            if status not in FAILURE_STATUSES and not retryable:
                continue
            listing_label = str(item.get("listing_label") or "")
            product_code = str(item.get("product_code") or "")
            image_set = str(item.get("image_set") or "")
            if not product_code and listing_label:
                product_code = listing_label.split("/", 1)[0]
            if not listing_label and product_code:
                listing_label = product_code if not image_set else f"{product_code}/{image_set}"
            if not listing_label:
                continue
            candidates.append(
                FailureCandidate(
                    item_id=make_failure_item_id(record.run_id, listing_label, product_code, image_set),
                    source_run_id=record.run_id,
                    account_id=record.account_id,
                    listing_label=listing_label,
                    product_code=product_code,
                    image_set=image_set,
                    merchant_code=str(item.get("platform_listing_code") or item.get("merchant_code") or ""),
                    item_status=status or "failed",
                    reason=str(item.get("reason") or ""),
                    error=str(item.get("error") or ""),
                    retryable=retryable or status in {"retryable", "submit_uncertain"},
                    started_at=record.started_at,
                )
            )
    return candidates


def sync_failure_items(limit_runs: int = 1000) -> tuple[int, int]:
    candidates = extract_failure_candidates(limit_runs=limit_runs)
    if not is_database_available():
        return len({c.source_run_id for c in candidates}), len(candidates)
    count = 0
    for c in candidates:
        row = upsert_failure_item(
            item_id=c.item_id,
            source_run_id=c.source_run_id,
            account_id=c.account_id,
            listing_label=c.listing_label,
            product_code=c.product_code,
            image_set=c.image_set,
            merchant_code=c.merchant_code,
            item_status=c.item_status,
            reason=c.reason,
            error=c.error,
            retryable=c.retryable,
        )
        if row:
            count += 1
    return len({c.source_run_id for c in candidates}), count


def list_failures(
    *,
    page: int,
    page_size: int,
    account_id: str = "",
    item_status: str = "",
    decision_status: str = "",
    product_code: str = "",
):
    sync_failure_items()
    if is_database_available():
        return search_failure_items(
            page=page,
            page_size=page_size,
            account_id=account_id,
            item_status=item_status,
            decision_status=decision_status,
            product_code=product_code,
        )

    candidates = extract_failure_candidates()
    filtered = [
        c
        for c in candidates
        if (not account_id or c.account_id == account_id)
        and (not item_status or c.item_status == item_status)
        and (not product_code or product_code.lower() in c.listing_label.lower())
        and (not decision_status or decision_status == "open")
    ]
    total = len(filtered)
    start = (max(1, page) - 1) * page_size
    return filtered[start : start + page_size], total


def mark_failure_item(item_id: str, decision_status: str, decision_note: str = ""):
    return update_failure_decision(
        item_id=item_id,
        decision_status=decision_status,
        decision_note=decision_note,
    )


def retry_failure_item(item_id: str, *, category_keyword: str = "") -> tuple[str, str]:
    item = get_failure_item(item_id)
    if not item:
        raise KeyError(item_id)
    settings = load_yaml_settings()
    run_id = create_listing_run(item.account_id)
    TaskRunStore().update_status(run_id, RunStatus.PENDING, "queued from failure workbench")
    enqueue_listing_task(
        run_id=run_id,
        account_id=item.account_id,
        product_codes=[item.product_code],
        dry_run=False,
        category_keyword=category_keyword or settings.listing.category_keyword,
        platform_listing_code=item.merchant_code,
        scheduled_at=datetime.now(),
        retry_item={
            "source_run_id": item.source_run_id,
            "listing_label": item.listing_label,
            "product_code": item.product_code,
            "image_set": item.image_set,
            "failure_item_id": item.item_id,
        },
    )
    update_failure_decision(
        item_id=item.item_id,
        decision_status="retrying",
        decision_note="manual retry queued",
        retry_run_id=run_id,
    )
    return item.item_id, run_id

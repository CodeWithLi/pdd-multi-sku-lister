"""Failure workbench APIs."""

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.failures import (
    FailureBulkMarkRequest,
    FailureItemOut,
    FailureListResponse,
    FailureMarkRequest,
    FailureRetryRequest,
    FailureRetryResponse,
    FailureRetryResult,
    FailureSyncResponse,
    ListingFailureDetailListResponse,
    ListingFailureDetailOut,
)
from pdd_agent.api.services.failure_workbench import (
    list_failures,
    mark_failure_item,
    retry_failure_item,
    sync_failure_items,
)
from pdd_agent.api.services.listing_failure_log import (
    get_failure_details_for_item,
    get_failure_details_for_run,
)
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/failures", tags=["failures"])


def _failure_out(row) -> FailureItemOut:
    return FailureItemOut(
        item_id=row.item_id,
        source_run_id=row.source_run_id,
        account_id=row.account_id,
        listing_label=row.listing_label,
        product_code=row.product_code,
        image_set=row.image_set or "",
        merchant_code=row.merchant_code or "",
        item_status=row.item_status,
        reason=row.reason or "",
        error=row.error or "",
        retryable=bool(row.retryable),
        decision_status=getattr(row, "decision_status", "open") or "open",
        decision_note=getattr(row, "decision_note", "") or "",
        retry_run_id=getattr(row, "retry_run_id", "") or "",
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


def _summary(items: list[FailureItemOut]) -> dict[str, int]:
    data = {"open": 0, "retrying": 0, "handled": 0, "ignored": 0}
    for item in items:
        data[item.decision_status] = data.get(item.decision_status, 0) + 1
    return data


def _detail_out(row) -> ListingFailureDetailOut:
    return ListingFailureDetailOut(
        detail_id=row.detail_id,
        failure_item_id=row.failure_item_id or "",
        source_run_id=row.source_run_id or "",
        account_id=row.account_id or "",
        listing_label=row.listing_label or "",
        product_code=row.product_code or "",
        image_set=row.image_set or "",
        family_code=row.family_code or "",
        merchant_code=row.merchant_code or "",
        phase=row.phase or "",
        step=row.step or "",
        severity=row.severity or "error",
        reason_code=row.reason_code or "",
        message=row.message or "",
        error=row.error or "",
        detail=row.detail if isinstance(row.detail, dict) else {},
        screenshot_path=row.screenshot_path or "",
        page_url=row.page_url or "",
        created_at=getattr(row, "created_at", None),
    )


@router.get("/{item_id}/details", response_model=ListingFailureDetailListResponse)
def failure_item_details(item_id: str, limit: int = Query(default=200, ge=1, le=500)):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL failure workbench unavailable")
    rows = get_failure_details_for_item(item_id, limit=limit)
    items = [_detail_out(r) for r in rows]
    return ListingFailureDetailListResponse(items=items, total=len(items))


@router.get("/details/by-run/{run_id}", response_model=ListingFailureDetailListResponse)
def failure_details_by_run(run_id: str, limit: int = Query(default=500, ge=1, le=1000)):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL failure workbench unavailable")
    rows = get_failure_details_for_run(run_id, limit=limit)
    items = [_detail_out(r) for r in rows]
    return ListingFailureDetailListResponse(items=items, total=len(items))


@router.post("/sync", response_model=FailureSyncResponse)
def sync_failures(limit_runs: int = Query(default=1000, ge=1, le=10000)):
    scanned, upserted = sync_failure_items(limit_runs=limit_runs)
    return FailureSyncResponse(scanned_runs=scanned, upserted_items=upserted)


@router.get("", response_model=FailureListResponse)
def failures_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    account_id: str = "",
    item_status: str = "",
    decision_status: str = "",
    product_code: str = "",
):
    rows, total = list_failures(
        page=page,
        page_size=page_size,
        account_id=account_id,
        item_status=item_status,
        decision_status=decision_status,
        product_code=product_code,
    )
    if total > 0 and not rows and page > 1:
        page = 1
        rows, total = list_failures(
            page=page,
            page_size=page_size,
            account_id=account_id,
            item_status=item_status,
            decision_status=decision_status,
            product_code=product_code,
        )
    items = [_failure_out(r) for r in rows]
    return FailureListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        summary=_summary(items),
    )


@router.post("/{item_id}/mark", response_model=FailureItemOut)
def mark_failure(item_id: str, body: FailureMarkRequest):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL failure workbench unavailable")
    row = mark_failure_item(item_id, body.decision_status, body.decision_note)
    if not row:
        raise HTTPException(status_code=404, detail=f"failure item not found: {item_id}")
    return _failure_out(row)


@router.post("/mark-bulk", response_model=list[FailureItemOut])
def mark_failures_bulk(body: FailureBulkMarkRequest):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL failure workbench unavailable")
    rows = []
    for item_id in body.item_ids:
        row = mark_failure_item(item_id, body.decision_status, body.decision_note)
        if row:
            rows.append(_failure_out(row))
    return rows


@router.post("/retry", response_model=FailureRetryResponse)
def retry_failures(body: FailureRetryRequest):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL failure workbench unavailable")
    results: list[FailureRetryResult] = []
    for item_id in body.item_ids:
        try:
            _, run_id = retry_failure_item(item_id, category_keyword=body.category_keyword)
            results.append(FailureRetryResult(item_id=item_id, run_id=run_id, status="queued"))
        except KeyError:
            results.append(FailureRetryResult(item_id=item_id, status="not_found", message="failure item not found"))
        except Exception as exc:
            results.append(FailureRetryResult(item_id=item_id, status="failed", message=str(exc)))
    return FailureRetryResponse(total=len(results), results=results)

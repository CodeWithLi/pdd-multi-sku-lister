"""上架失败明细：写入数据库，供人工排查。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pdd_agent.api.services.failure_workbench import make_failure_item_id, upsert_live_failure_item
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import insert_listing_failure_detail, list_listing_failure_details
from pdd_agent.db.session import is_database_available
from pdd_agent.domain.models import ListingUnit, PreflightIssue

logger = get_logger(__name__)

from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors


def _human_message(reason_code: str, error: str = "", message: str = "") -> str:
    if message:
        return message
    base = ListingErrors.label(reason_code or "", fallback=reason_code or ListingErrors.DEFAULT_LABEL)
    err = (error or "").strip()
    if err and err not in base:
        return f"{base}。详情：{err}"
    return base


def record_listing_failure_detail(
    *,
    source_run_id: str = "",
    account_id: str = "",
    listing_label: str = "",
    product_code: str = "",
    image_set: str = "",
    family_code: str = "",
    merchant_code: str = "",
    failure_item_id: str = "",
    phase: str = "",
    step: str = "",
    severity: str = "error",
    reason_code: str = "",
    message: str = "",
    error: str = "",
    detail: dict[str, Any] | None = None,
    screenshot_path: str = "",
    page_url: str = "",
) -> str | None:
    """写入一条上架失败/告警明细；数据库不可用时仅打日志。"""
    msg = _human_message(reason_code, error, message)
    detail_id = uuid.uuid4().hex[:24]
    if not failure_item_id and source_run_id and listing_label:
        failure_item_id = make_failure_item_id(
            source_run_id,
            listing_label,
            product_code,
            image_set,
        )

    if not is_database_available():
        logger.warning(
            "listing failure (db off) [%s] %s/%s %s: %s",
            account_id,
            phase,
            step,
            reason_code,
            msg,
        )
        return None

    try:
        insert_listing_failure_detail(
            detail_id=detail_id,
            failure_item_id=failure_item_id,
            source_run_id=source_run_id,
            account_id=account_id,
            listing_label=listing_label,
            product_code=product_code,
            image_set=image_set,
            family_code=family_code,
            merchant_code=merchant_code,
            phase=phase,
            step=step,
            severity=severity,
            reason_code=reason_code,
            message=msg,
            error=error or "",
            detail=detail or {},
            screenshot_path=screenshot_path,
            page_url=page_url,
        )
        logger.info(
            "listing failure recorded id=%s run=%s label=%s reason=%s",
            detail_id,
            source_run_id,
            listing_label,
            reason_code,
        )
        if source_run_id and listing_label and severity != "warning":
            upsert_live_failure_item(
                source_run_id=source_run_id,
                account_id=account_id,
                listing_label=listing_label,
                product_code=product_code,
                image_set=image_set,
                merchant_code=merchant_code,
                reason_code=reason_code,
                error=msg,
                severity=severity,
            )
        return detail_id
    except Exception as exc:
        logger.warning("listing failure insert failed: %s", exc)
        return None


def record_from_listing_result(
    *,
    source_run_id: str,
    account_id: str,
    result: dict[str, Any],
    phase: str = "upload",
    step: str = "final",
    screenshot_path: str = "",
    page_url: str = "",
) -> None:
    status = str(result.get("status") or "")
    if status in {"success", "listed"}:
        return
    listing_label = str(result.get("listing_label") or "")
    product_code = str(result.get("product_code") or "")
    image_set = str(result.get("image_set") or "")
    reason_code = str(result.get("reason") or status or "failed")
    error = str(result.get("error") or "")
    detail: dict[str, Any] = {
        "status": status,
        "retryable": bool(result.get("retryable")),
        "title": result.get("title") or "",
        "legacy_status": result.get("legacy_status") or "",
        "platform_listing_code": result.get("platform_listing_code") or "",
        "pdd_product_id_capture_status": result.get("pdd_product_id_capture_status") or "",
        "pdd_product_capture_message": result.get("pdd_product_capture_message") or "",
    }
    if isinstance(result.get("failure_details"), list):
        detail["timeline"] = result["failure_details"]

    record_listing_failure_detail(
        source_run_id=source_run_id,
        account_id=account_id,
        listing_label=listing_label,
        product_code=product_code,
        image_set=image_set,
        family_code=str(result.get("family_code") or ""),
        merchant_code=str(result.get("platform_listing_code") or result.get("merchant_code") or ""),
        phase=phase,
        step=step,
        severity="error",
        reason_code=reason_code,
        error=error,
        detail=detail,
        screenshot_path=screenshot_path,
        page_url=page_url,
    )


def record_preflight_issue(
    *,
    source_run_id: str,
    account_id: str,
    issue: PreflightIssue,
) -> None:
    level = issue.level or "error"
    reason_code = str(issue.reason_code or "").strip() or ListingErrorCode.PREFLIGHT_CATALOG
    if not issue.reason_code:
        if "无有效 SKU" in issue.message:
            reason_code = ListingErrorCode.PREFLIGHT_NO_SKUS
        elif "主图为空" in issue.message:
            reason_code = ListingErrorCode.PREFLIGHT_NO_CAROUSEL
        elif "详情图为空" in issue.message:
            reason_code = ListingErrorCode.PREFLIGHT_NO_DETAIL
        elif "商品表" in issue.message or "Excel" in issue.message:
            reason_code = ListingErrorCode.PREFLIGHT_CATALOG

    record_listing_failure_detail(
        source_run_id=source_run_id,
        account_id=account_id,
        listing_label=issue.listing_label or "",
        product_code=(issue.listing_label or "").split("/", 1)[0],
        phase="preflight",
        step="validate_assets",
        severity="warning" if level == "warning" else "error",
        reason_code=reason_code,
        message=issue.listing_label or issue.message,
        detail={"preflight_level": level},
    )


def validate_unit_image_files(
    unit: ListingUnit,
    *,
    source_run_id: str = "",
    account_id: str = "",
) -> list[str]:
    """检查主图/详情/预览图是否存在；缺失则写入失败明细。"""
    missing: list[str] = []
    checks: list[tuple[str, str]] = []
    for path in unit.carousel_images:
        checks.append(("carousel", str(path)))
    for path in unit.detail_images:
        checks.append(("detail", str(path)))
    for sku in unit.skus:
        if sku.preview_image:
            checks.append((f"preview:{sku.style_name}/{sku.model_name}", str(sku.preview_image)))

    for kind, path_str in checks:
        from pathlib import Path

        path = Path(path_str)
        if not path.is_file():
            missing.append(path_str)
            record_listing_failure_detail(
                source_run_id=source_run_id,
                account_id=account_id,
                listing_label=unit.listing_label,
                product_code=unit.product_code,
                image_set=unit.image_set,
                family_code=unit.family_code,
                merchant_code=unit.merchant_code,
                phase="preflight",
                step="check_image_files",
                severity="error",
                reason_code=ListingErrorCode.IMAGE_FILE_MISSING,
                message=ListingErrors.Msg.IMAGE_FILE_BAD.format(kind=kind),
                error=path_str,
                detail={"image_kind": kind, "path": path_str},
            )
    return missing


def record_price_fill_summary(
    *,
    source_run_id: str,
    account_id: str,
    unit: ListingUnit,
    filled: int,
    total: int,
    failed_items: list[dict[str, Any]],
    style_names: list[str],
    size_names: list[str],
) -> None:
    if filled >= total:
        return
    record_listing_failure_detail(
        source_run_id=source_run_id,
        account_id=account_id,
        listing_label=unit.listing_label,
        product_code=unit.product_code,
        image_set=unit.image_set,
        family_code=unit.family_code,
        merchant_code=unit.merchant_code,
        phase="price_fill",
        step="fill_inventory_price",
        severity="error",
        reason_code=ListingErrorCode.PRICE_FILL_PARTIAL,
        message=ListingErrors.Msg.PRICE_FILL_PARTIAL.format(filled=filled, total=total),
        detail={
            "filled": filled,
            "total": total,
            "style_names": style_names,
            "size_names": size_names,
            "failed_rows": failed_items,
            "skus": [
                {
                    "style": s.style_name,
                    "size": s.model_name,
                    "combo_folder": s.combo_folder,
                }
                for s in unit.skus
            ],
        },
    )
    for item in failed_items:
        reason = str(item.get("reason") or "row_not_found")
        code = ListingErrorCode.PRICE_FILL_ROW_NOT_FOUND
        if reason == "fill_by_index_failed":
            code = ListingErrorCode.PRICE_FILL_BY_INDEX_FAILED
        record_listing_failure_detail(
            source_run_id=source_run_id,
            account_id=account_id,
            listing_label=unit.listing_label,
            product_code=unit.product_code,
            image_set=unit.image_set,
            family_code=unit.family_code,
            phase="price_fill",
            step="fill_row",
            severity="error",
            reason_code=code,
            message=f"规格行填写失败：{item.get('style')} / {item.get('size')}",
            detail=dict(item),
        )


def persist_listing_run_failures(
    *,
    source_run_id: str,
    account_id: str,
    result: dict[str, Any],
) -> int:
    """任务结束时补录 preflight 错误与运行级 errors（浏览器内失败已在 upload 中实时写入）。"""
    count = 0
    preflight = result.get("preflight")
    issues: list[Any] = []
    if preflight is not None:
        if isinstance(preflight, dict):
            issues = list(preflight.get("issues") or [])
        else:
            issues = list(getattr(preflight, "issues", None) or [])

    for issue in issues:
        if isinstance(issue, PreflightIssue):
            if issue.level == "error":
                record_preflight_issue(source_run_id=source_run_id, account_id=account_id, issue=issue)
                count += 1
        elif isinstance(issue, dict) and str(issue.get("level") or "") == "error":
            record_listing_failure_detail(
                source_run_id=source_run_id,
                account_id=account_id,
                listing_label=str(issue.get("listing_label") or ""),
                phase="preflight",
                step="validate",
                severity="error",
                reason_code="preflight_catalog",
                message=str(issue.get("message") or ""),
            )
            count += 1

    for err in result.get("errors") or []:
        text = str(err or "").strip()
        if not text:
            continue
        record_listing_failure_detail(
            source_run_id=source_run_id,
            account_id=account_id,
            listing_label="",
            phase="listing",
            step="run_error",
            severity="error",
            reason_code="unexpected_error",
            message=text,
        )
        count += 1
    return count


def get_failure_details_for_item(item_id: str, limit: int = 200) -> list[Any]:
    return list_listing_failure_details(failure_item_id=item_id, limit=limit)


def get_failure_details_for_run(source_run_id: str, limit: int = 500) -> list[Any]:
    return list_listing_failure_details(source_run_id=source_run_id, limit=limit)

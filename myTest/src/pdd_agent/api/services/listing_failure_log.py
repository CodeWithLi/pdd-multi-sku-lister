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

# 机器 reason → 人工可读说明（可再拼接 error 字段里的具体信息）
REASON_LABELS: dict[str, str] = {
    "preview_not_ready": "预览图未全部上传，页面仍有规格行缺图",
    "preview_missing": "页面提示预览图缺失或未通过校验",
    "platform_listing_code_not_filled": "底部商品编码未填写",
    "platform_listing_code_verify_failed": "底部商品编码与期望货号不一致",
    "validation_errors": "提交前页面校验失败（库存/价格等未填完整）",
    "validation_incomplete": "提交前页面校验未通过（信息不完整）",
    "validation_required": "提交前页面有必填项未处理",
    "submit_blocked": "点击提交被页面拦截（通常仍有红色错误项）",
    "submit_uncertain": "提交结果不确定，需人工到在售/驳回列表核对",
    "submit_button_missing": "未找到「提交并上架」按钮",
    "submit_exception": "点击提交时发生异常",
    "listed": "已提交但后续抓取商品 ID 失败",
    "rejected_after_publish": "提交后被平台驳回",
    "published_but_not_found_in_on_sale_or_rejected": "提交后未在售列表/驳回列表中找到商品",
    "needs_manual_login_or_captcha": "需要人工登录或处理验证码/滑块",
    "page_or_material_changed": "页面结构或素材异常（分类/规格/上传相关）",
    "browser_transient_error": "浏览器超时或连接断开",
    "unexpected_error": "未分类的运行异常",
    "preflight_no_skus": "上架前校验：无有效 SKU",
    "preflight_no_carousel": "上架前校验：主图为空",
    "preflight_no_detail": "上架前校验：详情图为空",
    "preflight_catalog": "上架前校验：商品表或素材目录问题",
    "image_file_missing": "图片文件不存在或无法读取",
    "price_fill_partial": "价格表文字字段未全部填写（库存/拼团价/单买价/编码）",
    "price_fill_row_not_found": "价格表找不到对应规格行",
    "price_fill_by_index_failed": "按行号填写价格表失败",
    "catalog_parse_warning": "素材目录解析警告",
    "no_valid_units": "无有效上架单元",
}


def _human_message(reason_code: str, error: str = "", message: str = "") -> str:
    if message:
        return message
    base = REASON_LABELS.get(reason_code or "", reason_code or "上架失败")
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
    reason_code = "preflight_catalog"
    if "无有效 SKU" in issue.message:
        reason_code = "preflight_no_skus"
    elif "主图为空" in issue.message:
        reason_code = "preflight_no_carousel"
    elif "详情图为空" in issue.message:
        reason_code = "preflight_no_detail"
    elif "商品表" in issue.message or "Excel" in issue.message:
        reason_code = "preflight_catalog"

    record_listing_failure_detail(
        source_run_id=source_run_id,
        account_id=account_id,
        listing_label=issue.listing_label or "",
        product_code=(issue.listing_label or "").split("/", 1)[0],
        phase="preflight",
        step="validate_assets",
        severity="warning" if level == "warning" else "error",
        reason_code=reason_code,
        message=issue.message,
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
                reason_code="image_file_missing",
                message=f"图片无法打开或不存在（{kind}）",
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
        reason_code="price_fill_partial",
        message=f"价格表仅填写 {filled}/{total} 行，其余行库存/价格/编码未写入",
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
        code = "price_fill_row_not_found"
        if reason == "fill_by_index_failed":
            code = "price_fill_by_index_failed"
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

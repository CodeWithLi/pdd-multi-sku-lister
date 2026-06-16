"""整合链路专用报错记录（独立于 listing_failure_log / run_records）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.models import IntegratedPipelineORM
from pdd_agent.db.repositories import (
    count_pipeline_issue_reports,
    get_pipeline_issue_report,
    insert_pipeline_issue_report,
    search_pipeline_issue_reports,
)
from pdd_agent.db.session import is_database_available
from pdd_agent.domain.enums import AgentKind

logger = get_logger(__name__)

STAGE_LABELS = {
    "listing": "上架",
    "campaign": "活动报名",
    "traffic": "推广",
    "orchestration": "链路编排",
    "scheduling": "任务调度",
}

ISSUE_TITLE_MAP: dict[str, str] = {
  # listing
    "preview_not_ready": "预览图未就绪",
    "preview_missing": "预览图缺失",
    "platform_listing_code_not_filled": "商品编码未填写",
    "platform_listing_code_verify_failed": "商品编码校验失败",
    "validation_errors": "页面校验失败",
    "validation_incomplete": "页面信息不完整",
    "validation_required": "必填项未处理",
    "submit_blocked": "提交被拦截",
    "submit_uncertain": "提交结果不确定",
    "submit_button_missing": "未找到提交按钮",
    "submit_exception": "提交异常",
    "listed": "提交后抓取商品 ID 失败",
    "rejected_after_publish": "平台驳回",
    "published_but_not_found_in_on_sale_or_rejected": "提交后未找到商品",
    "needs_manual_login_or_captcha": "需人工登录/验证码",
    "page_or_material_changed": "页面或素材异常",
    "browser_transient_error": "浏览器超时或连接异常",
    "browser_manually_closed": "浏览器被手动关闭",
    "unexpected_error": "未分类异常",
    "preflight_no_skus": "SKU 编码无效或找不到",
    "preflight_no_carousel": "主图为空",
    "preflight_no_detail": "详情图为空",
    "preflight_catalog": "商品表/素材目录问题",
    "image_file_missing": "图片文件缺失",
    "price_fill_partial": "价格表未填完整",
    "price_fill_row_not_found": "价格表找不到规格行",
    "price_fill_by_index_failed": "按行号填价失败",
    "catalog_parse_warning": "素材目录解析警告",
    "no_valid_units": "无有效上架单元",
    "slot_alignment_failed": "槽位对齐失败",
    "sku_not_found": "SKU 编码找不到对应商品",
    "merchant_code_mismatch": "货号/编码不匹配",
    # campaign
    "product_time_requirement_not_met": "商品上架未满活动要求时长",
    "product_not_eligible_for_activity": "商品不可报名该活动",
    "activity_register_failed": "活动报名失败",
    "activity_search_failed": "活动搜索失败",
    "price_check_failed": "活动价格校验未通过",
    "modal_eligibility_failed": "活动资格校验未通过",
    # traffic
    "promotion_create_failed": "推广创建失败",
    "promotion_budget_failed": "推广预算设置失败",
    # orchestration
    "listing_no_pdd_ids": "上架完成但未拿到拼多多商品 ID",
    "listing_failed": "上架步骤失败",
    "activity_failed": "活动步骤失败",
    "traffic_failed": "推广步骤失败",
    "pipeline_canceled": "链路被用户取消",
    "queue_exception": "队列执行异常",
    "browser_closed": "浏览器被手动关闭",
    "skip_listing_lookup_failed": "跳过上架时找不到在售记录",
    "task_canceled": "任务被取消",
}

BROWSER_CLOSED_HINTS = (
    "target closed",
    "browser has been closed",
    "connection closed",
    "browser closed",
    "page closed",
    "context closed",
    "playwright",
    "target page, context or browser has been closed",
)


def _issue_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _pipeline_batch_id(row: IntegratedPipelineORM | None) -> str:
    if not row:
        return ""
    meta = row.meta if isinstance(row.meta, dict) else {}
    return str(meta.get("batch_id") or "")


def _human_title(reason_code: str, fallback: str = "") -> str:
    code = str(reason_code or "").strip()
    if code in ISSUE_TITLE_MAP:
        return ISSUE_TITLE_MAP[code]
    fb = str(fallback or "").strip()
    if fb:
        return fb[:120]
    if code:
        return code
    return "整合链路异常"


def _compose_message(title: str, error: str = "", extra: str = "") -> str:
    parts = [title]
    err = str(error or "").strip()
    ext = str(extra or "").strip()
    if ext and ext not in title:
        parts.append(ext)
    if err and err not in title and err not in ext:
        parts.append(err)
    return " — ".join(parts)


def _detect_browser_closed(error: str) -> bool:
    low = str(error or "").lower()
    return any(hint in low for hint in BROWSER_CLOSED_HINTS)


def _normalize_listing_reason(reason: str, error: str) -> str:
    code = str(reason or "").strip()
    if code == "browser_manually_closed" or _detect_browser_closed(error):
        return "browser_manually_closed"
    if code:
        return code
    return _infer_reason_from_error(error)


def _infer_reason_from_error(error: str) -> str:
    if _detect_browser_closed(error):
        return "browser_manually_closed"
    low = str(error or "").lower()
    if "sku" in low and ("not found" in low or "找不到" in error or "无效" in error):
        return "sku_not_found"
    if "预览" in error or "preview" in low:
        return "preview_not_ready"
    if "编码" in error or "merchant" in low:
        return "merchant_code_mismatch"
    return "unexpected_error"


def record_pipeline_issue(
    *,
    pipeline_id: str,
    account_id: str = "",
    batch_id: str = "",
    stage: str = "orchestration",
    chain_step: str = "",
    severity: str = "error",
    reason_code: str = "",
    title: str = "",
    message: str = "",
    error_text: str = "",
    context: dict[str, Any] | None = None,
    run_id: str = "",
    activity_id: str = "",
    product_selector: str = "",
    source_location: str = "",
) -> str | None:
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id or not is_database_available():
        return None
    issue_id = _issue_id()
    final_title = title or _human_title(reason_code, chain_step)
    final_message = message or _compose_message(final_title, error_text)
    try:
        insert_pipeline_issue_report(
            issue_id=issue_id,
            pipeline_id=pipeline_id,
            batch_id=batch_id,
            account_id=account_id,
            stage=stage,
            chain_step=chain_step,
            severity=severity,
            reason_code=reason_code,
            title=final_title,
            message=final_message,
            error_text=error_text,
            context=context,
            run_id=run_id,
            activity_id=activity_id,
            product_selector=product_selector,
            source_location=source_location,
        )
        logger.info(
            "pipeline issue recorded issue_id=%s pipeline=%s stage=%s reason=%s",
            issue_id,
            pipeline_id,
            stage,
            reason_code,
        )
        return issue_id
    except Exception:
        logger.exception("record pipeline issue failed pipeline_id=%s", pipeline_id)
        return None


def _base_fields(row: IntegratedPipelineORM | None, *, pipeline_id: str) -> dict[str, str]:
    if row:
        return {
            "pipeline_id": row.pipeline_id,
            "account_id": row.account_id,
            "batch_id": _pipeline_batch_id(row),
        }
    return {"pipeline_id": pipeline_id, "account_id": "", "batch_id": ""}


def _product_selector_from_item(item: dict[str, Any]) -> str:
    listing_label = str(item.get("listing_label") or "").strip()
    if listing_label:
        return listing_label
    product_code = str(item.get("product_code") or "").strip()
    family = str(item.get("family_code") or item.get("image_set") or "").strip()
    if family and product_code:
        return f"{family}/{product_code}"
    return product_code


def _ingest_listing_items(
    *,
    base: dict[str, str],
    run_id: str,
    result: dict[str, Any],
    top_error: str,
) -> list[str]:
    recorded: list[str] = []
    items: list[dict[str, Any]] = []
    for key in ("results", "units"):
        for raw in result.get(key) or []:
            if isinstance(raw, dict):
                items.append(raw)

    for item in items:
        status = str(item.get("status") or "").lower()
        if status not in {"failed", "retryable", "error"}:
            continue
        error = str(item.get("error") or "").strip()
        reason = _normalize_listing_reason(
            str(item.get("reason") or item.get("reason_code") or "").strip(),
            error or top_error,
        )
        step = str(item.get("step") or item.get("phase") or "").strip()
        if not reason and error:
            reason = _infer_reason_from_error(error)
        title = _human_title(reason, step or "上架失败")
        severity = "critical" if reason in {"browser_manually_closed", "browser_closed"} else "error"
        issue_id = record_pipeline_issue(
            **base,
            stage="listing",
            chain_step=step or "listing_item_failed",
            severity=severity,
            reason_code=reason or "listing_failed",
            title=title,
            message=_compose_message(title, error, str(item.get("message") or "")),
            error_text=error or top_error,
            context={"item": item},
            run_id=run_id,
            product_selector=_product_selector_from_item(item),
            source_location="pipeline_issue_report_service._ingest_listing_items",
        )
        if issue_id:
            recorded.append(issue_id)

    for err in result.get("errors") or []:
        text = str(err or "").strip()
        if not text:
            continue
        reason = _infer_reason_from_error(text)
        severity = "critical" if reason in {"browser_manually_closed", "browser_closed"} else "error"
        issue_id = record_pipeline_issue(
            **base,
            stage="listing",
            chain_step="listing_graph_error",
            severity=severity,
            reason_code=reason,
            title=_human_title(reason, "上架图执行错误"),
            message=text,
            error_text=text,
            context={"graph_error": text},
            run_id=run_id,
            source_location="pipeline_issue_report_service._ingest_listing_items",
        )
        if issue_id:
            recorded.append(issue_id)

    return recorded


def _ingest_campaign_items(
    *,
    base: dict[str, str],
    run_id: str,
    result: dict[str, Any],
    top_error: str,
    activity_id: str = "",
) -> list[str]:
    recorded: list[str] = []
    skip_steps = {"product_time_requirement_not_met", "product_not_eligible_for_activity"}

    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").lower()
        step = str(item.get("step") or "").strip()
        error = str(item.get("error") or "").strip()
        if status == "success" and not error:
            continue
        reason = step if step in ISSUE_TITLE_MAP else str(item.get("reason") or "").strip()
        if not reason:
            reason = _infer_reason_from_error(error or top_error)
        severity = "warning" if step in skip_steps or reason in skip_steps else "error"
        title = _human_title(reason, step or "活动报名失败")
        issue_id = record_pipeline_issue(
            **base,
            stage="campaign",
            chain_step=step or "campaign_item_failed",
            severity=severity,
            reason_code=reason or "activity_register_failed",
            title=title,
            message=_compose_message(title, error or top_error),
            error_text=error or top_error,
            context={"item": item},
            run_id=run_id,
            activity_id=activity_id,
            source_location="pipeline_issue_report_service._ingest_campaign_items",
        )
        if issue_id:
            recorded.append(issue_id)

    for err in result.get("errors") or []:
        text = str(err or "").strip()
        if not text:
            continue
        reason = _infer_reason_from_error(text)
        issue_id = record_pipeline_issue(
            **base,
            stage="campaign",
            chain_step="campaign_graph_error",
            severity="error",
            reason_code=reason,
            title=_human_title(reason, "活动报名错误"),
            message=text,
            error_text=text,
            context={"graph_error": text, "activity_id": activity_id},
            run_id=run_id,
            activity_id=activity_id,
            source_location="pipeline_issue_report_service._ingest_campaign_items",
        )
        if issue_id:
            recorded.append(issue_id)

    return recorded


def _ingest_traffic_items(
    *,
    base: dict[str, str],
    run_id: str,
    result: dict[str, Any],
    top_error: str,
) -> list[str]:
    recorded: list[str] = []

    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").lower()
        step = str(item.get("step") or "").strip()
        error = str(item.get("error") or "").strip()
        if status == "success" and not error:
            continue
        reason = step if step in ISSUE_TITLE_MAP else "promotion_create_failed"
        title = _human_title(reason, step or "推广创建失败")
        issue_id = record_pipeline_issue(
            **base,
            stage="traffic",
            chain_step=step or "traffic_item_failed",
            severity="error",
            reason_code=reason,
            title=title,
            message=_compose_message(title, error or top_error),
            error_text=error or top_error,
            context={"item": item},
            run_id=run_id,
            source_location="pipeline_issue_report_service._ingest_traffic_items",
        )
        if issue_id:
            recorded.append(issue_id)

    for err in result.get("errors") or []:
        text = str(err or "").strip()
        if not text:
            continue
        reason = _infer_reason_from_error(text)
        issue_id = record_pipeline_issue(
            **base,
            stage="traffic",
            chain_step="traffic_graph_error",
            severity="error",
            reason_code=reason,
            title=_human_title(reason, "推广执行错误"),
            message=text,
            error_text=text,
            context={"graph_error": text},
            run_id=run_id,
            source_location="pipeline_issue_report_service._ingest_traffic_items",
        )
        if issue_id:
            recorded.append(issue_id)

    return recorded


def ingest_queue_task_outcome(
    *,
    pipeline_row: IntegratedPipelineORM | None,
    pipeline_id: str,
    agent: str,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> list[str]:
    """队列任务结束时写入整合链路报错（仅 pipeline 上下文）。"""
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id:
        return []
    base = _base_fields(pipeline_row, pipeline_id=pipeline_id)
    result = result if isinstance(result, dict) else {}
    top_error = str(error or result.get("error") or "").strip()
    recorded: list[str] = []

    if agent == AgentKind.LISTING.value:
        recorded.extend(
            _ingest_listing_items(base=base, run_id=run_id, result=result, top_error=top_error)
        )
    elif agent == AgentKind.CAMPAIGN.value:
        activity_id = ""
        if pipeline_row:
            meta = pipeline_row.meta if isinstance(pipeline_row.meta, dict) else {}
            ids = meta.get("activity_ids") or []
            idx = int(meta.get("campaign_activity_index") or 0)
            if isinstance(ids, list) and idx < len(ids):
                activity_id = str(ids[idx] or pipeline_row.activity_id or "")
            else:
                activity_id = str(pipeline_row.activity_id or "")
        recorded.extend(
            _ingest_campaign_items(
                base=base,
                run_id=run_id,
                result=result,
                top_error=top_error,
                activity_id=activity_id,
            )
        )
    elif agent == AgentKind.TRAFFIC.value:
        recorded.extend(
            _ingest_traffic_items(base=base, run_id=run_id, result=result, top_error=top_error)
        )

    if not success and not recorded:
        reason = _infer_reason_from_error(top_error)
        stage = {
            AgentKind.LISTING.value: "listing",
            AgentKind.CAMPAIGN.value: "campaign",
            AgentKind.TRAFFIC.value: "traffic",
        }.get(agent, "orchestration")
        chain_step = f"{stage}_failed"
        severity = "critical" if reason in {"browser_manually_closed", "browser_closed"} else "error"
        issue_id = record_pipeline_issue(
            **base,
            stage=stage,
            chain_step=chain_step,
            severity=severity,
            reason_code=reason,
            title=_human_title(reason, chain_step),
            message=top_error or _human_title(reason, chain_step),
            error_text=top_error,
            context={"result": result},
            run_id=run_id,
            source_location="pipeline_issue_report_service.ingest_queue_task_outcome",
        )
        if issue_id:
            recorded.append(issue_id)

    return recorded


def ingest_orchestration_issue(
    *,
    pipeline_row: IntegratedPipelineORM | None,
    pipeline_id: str,
    chain_step: str,
    reason_code: str,
    message: str,
    error_text: str = "",
    severity: str = "error",
    run_id: str = "",
    activity_id: str = "",
    product_selector: str = "",
    context: dict[str, Any] | None = None,
    source_location: str = "",
) -> str | None:
    base = _base_fields(pipeline_row, pipeline_id=pipeline_id)
    return record_pipeline_issue(
        **base,
        stage="orchestration",
        chain_step=chain_step,
        severity=severity,
        reason_code=reason_code,
        title=_human_title(reason_code, chain_step),
        message=message,
        error_text=error_text or message,
        context=context,
        run_id=run_id,
        activity_id=activity_id,
        product_selector=product_selector,
        source_location=source_location or "pipeline_issue_report_service.ingest_orchestration_issue",
    )


def ingest_queue_exception(
    *,
    pipeline_row: IntegratedPipelineORM | None,
    pipeline_id: str,
    agent: str,
    run_id: str,
    exc: BaseException,
) -> str | None:
    text = str(exc)
    reason = "browser_closed" if _detect_browser_closed(text) else "queue_exception"
    return ingest_orchestration_issue(
        pipeline_row=pipeline_row,
        pipeline_id=pipeline_id,
        chain_step="queue_exception",
        reason_code=reason,
        message=f"队列执行异常（{agent}）：{text}",
        error_text=text,
        severity="critical" if reason == "browser_closed" else "error",
        run_id=run_id,
        context={"agent": agent, "exception_type": type(exc).__name__},
        source_location="pipeline_issue_report_service.ingest_queue_exception",
    )


def ingest_pipeline_canceled(
    *,
    pipeline_row: IntegratedPipelineORM | None,
    pipeline_id: str,
    pending_run_ids: list[str] | None = None,
) -> str | None:
    return ingest_orchestration_issue(
        pipeline_row=pipeline_row,
        pipeline_id=pipeline_id,
        chain_step="canceled",
        reason_code="pipeline_canceled",
        message="用户取消了整合链路，后续活动报名与推广不再执行",
        severity="warning",
        context={"pending_run_ids": list(pending_run_ids or [])},
        source_location="pipeline_issue_report_service.ingest_pipeline_canceled",
    )


def list_pipeline_issues(
    *,
    page: int = 1,
    page_size: int = 50,
    pipeline_id: str = "",
    batch_id: str = "",
    account_id: str = "",
    stage: str = "",
    severity: str = "",
    keyword: str = "",
) -> dict[str, Any]:
    rows, total = search_pipeline_issue_reports(
        page=page,
        page_size=page_size,
        pipeline_id=pipeline_id,
        batch_id=batch_id,
        account_id=account_id,
        stage=stage,
        severity=severity,
        keyword=keyword,
    )
    return {
        "items": [issue_to_dict(row) for row in rows],
        "total": total,
        "page": max(1, page),
        "page_size": max(1, min(200, page_size)),
    }


def get_pipeline_issue(issue_id: str) -> dict[str, Any] | None:
    row = get_pipeline_issue_report(issue_id)
    return issue_to_dict(row) if row else None


def pipeline_issue_summary(pipeline_id: str) -> dict[str, int]:
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id:
        return {"total": 0, "error": 0, "warning": 0, "critical": 0}
    return {
        "total": count_pipeline_issue_reports(pipeline_id=pipeline_id),
        "error": count_pipeline_issue_reports(pipeline_id=pipeline_id, severity="error"),
        "warning": count_pipeline_issue_reports(pipeline_id=pipeline_id, severity="warning"),
        "critical": count_pipeline_issue_reports(pipeline_id=pipeline_id, severity="critical"),
    }


def issue_to_dict(row) -> dict[str, Any]:
    if not row:
        return {}
    stage = str(row.stage or "")
    return {
        "issue_id": row.issue_id,
        "pipeline_id": row.pipeline_id,
        "batch_id": row.batch_id or "",
        "account_id": row.account_id,
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "chain_step": row.chain_step or "",
        "severity": row.severity or "error",
        "reason_code": row.reason_code or "",
        "title": row.title or "",
        "message": row.message or "",
        "error_text": row.error_text or "",
        "context": row.context if isinstance(row.context, dict) else {},
        "run_id": row.run_id or "",
        "activity_id": row.activity_id or "",
        "product_selector": row.product_selector or "",
        "source_location": row.source_location or "",
        "created_at": row.created_at,
    }

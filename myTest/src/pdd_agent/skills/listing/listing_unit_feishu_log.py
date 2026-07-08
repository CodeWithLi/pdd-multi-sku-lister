"""单单元上架结果即时写入飞书（成功/失败），避免多单元批次结束时才落表。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.domain.models import ListingUnit


def _safe_exc(exc: BaseException) -> str:
    return str(exc or "").strip()


def schedule_listing_unit_failure_to_feishu(
    account_id: str,
    unit: ListingUnit,
    item_result: dict[str, Any],
    *,
    run_id: str = "",
) -> bool:
    """单元上架失败/跳过后立即写入飞书失败表；返回是否已调度。"""
    status = str(item_result.get("status") or "").strip().lower()
    if status in {"success", "listed"}:
        return False
    if status not in {"failed", "retryable", "skipped"} and not item_result.get("error"):
        return False
    if item_result.get("feishu_failure_logged"):
        return False

    try:
        from pdd_agent.api.services.task_runner import _account_display_name, _listing_run_timing
        from pdd_agent.integrations.feishu.config import load_feishu_config
        from pdd_agent.integrations.feishu.pdd_upload_sync import (
            _format_brief_listing_failure_reason,
            map_listing_failure_record_type,
            schedule_pdd_upload_failure_log,
        )

        cfg = load_feishu_config()
        if not cfg.pdd_upload_log.failure_log_enabled:
            return False

        reason_code = str(item_result.get("reason") or item_result.get("reason_code") or "")
        from pdd_agent.api.services.listing_preflight_feishu_bridge import (
            is_preflight_feishu_bridge_reason,
        )

        if is_preflight_feishu_bridge_reason(reason_code):
            return False

        error = str(item_result.get("error") or item_result.get("message") or "")
        merchant_code = str(
            item_result.get("platform_listing_code")
            or item_result.get("merchant_code")
            or unit.merchant_code
            or unit.product_code
            or ""
        ).strip()
        brief = _format_brief_listing_failure_reason(
            listing_label=unit.listing_label,
            reason_code=reason_code,
            error=error,
            message=error,
            merchant_code=merchant_code,
        )
        publish_start, publish_end = _listing_run_timing(run_id)
        duration_seconds: float | None = None
        if publish_start and publish_end:
            duration_seconds = max(0.0, (publish_end - publish_start).total_seconds())

        schedule_pdd_upload_failure_log(
            account_id=account_id,
            account_name=_account_display_name(account_id),
            listing_label=unit.listing_label,
            merchant_code=merchant_code,
            record_type=map_listing_failure_record_type(
                status=status,
                reason_code=reason_code,
                retryable=bool(item_result.get("retryable")),
                legacy_status=str(item_result.get("legacy_status") or ""),
            ),
            reason_code=reason_code,
            error=error,
            message=brief or error or unit.listing_label,
            failure_reason=brief or error or unit.listing_label,
            system_reason=error[:2000],
            publish_start=publish_start,
            publish_end=publish_end or datetime.now(),
            duration_seconds=duration_seconds,
            fallback_product_code=unit.product_code,
        )
        item_result["feishu_failure_logged"] = True
        return True
    except Exception as exc:
        print(
            f"[{account_id}] [{unit.listing_label}] 飞书失败日志调度失败：{_safe_exc(exc)}",
            flush=True,
        )
        return False

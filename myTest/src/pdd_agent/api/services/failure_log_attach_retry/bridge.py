"""
失败日志挂回原链路重跑 — 薄桥接。

仅在 cycle_relist trigger / pipeline_service / task_queue / pipelines 路由引用。
"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)


def is_attach_source_pipeline_enabled(watch) -> bool:
    if watch is None:
        return False
    return bool(getattr(watch, "attach_source_pipeline_enabled", False))


def try_process_attach_source_pipeline(
    candidate: dict[str, Any],
    *,
    config=None,
    watch=None,
    skip_claim: bool = False,
    trigger_source: str = "auto_watch",
    base: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    「挂回原链路」+「抓取链路 ID」同时开启时处理失败日志挂回原链路。

    返回 dict 表示已接管（含 skip / error）；返回 None 表示走旧整链逻辑。
    """
    from pdd_agent.integrations.feishu.config import load_feishu_config
    from pdd_agent.api.services.failure_log_attach_retry.capture_pipeline_id import (
        evaluate_capture_pipeline_id_gate,
        is_attach_path_fully_enabled,
    )

    cfg = config or load_feishu_config()
    watch_cfg = watch or cfg.pdd_upload_log.failure_cycle_relist_watch
    # 两个开关都开才接管；只开挂回未开抓取 → 仍走旧整链
    if not is_attach_path_fully_enabled(watch_cfg):
        return None

    from pdd_agent.api.services.failure_log_attach_retry.policy import (
        start_attach_retry_on_source_pipeline,
    )
    from pdd_agent.core.account_display import resolve_cycle_relist_account_id
    from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim import try_claim_cycle_relist
    from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger import (
        check_merchant_code_already_on_sale,
    )

    record_id = str(candidate.get("record_id") or "").strip()
    merchant_code = str(candidate.get("merchant_code") or "").strip()
    account_name = str(candidate.get("account_name") or "").strip()
    account_id_hint = str(candidate.get("account_id") or "").strip()
    report_platform = str(candidate.get("report_platform") or "").strip()

    gate = evaluate_capture_pipeline_id_gate(candidate, watch=watch_cfg)
    source_pipeline_id = str(gate.get("pipeline_id") or "").strip()

    out = dict(base or {})
    out.update(
        {
            "ok": False,
            "record_id": record_id,
            "merchant_code": merchant_code,
            "account_name": account_name,
            "account_id": str(out.get("account_id") or ""),
            "pipeline_id": "",
            "source_pipeline_id": source_pipeline_id,
            "claim": out.get("claim") or {},
            "error": "",
            "skipped": False,
            "reason": "",
            "attach_source_pipeline": True,
            "capture_pipeline_id": True,
        }
    )

    if not record_id:
        out["error"] = "record_id 为空"
        return out

    allowed_platforms = {
        str(x).strip()
        for x in (watch_cfg.pipeline_report_platforms or [])
        if str(x).strip()
    }
    if allowed_platforms and report_platform and report_platform not in allowed_platforms:
        out.update(ok=True, skipped=True, reason="report_platform_filtered")
        return out

    if gate.get("skipped") or not source_pipeline_id:
        out.update(ok=True, skipped=True, reason="missing_source_pipeline_id")
        return out

    account_id, account_error = resolve_cycle_relist_account_id(
        account_name=account_name,
        account_id=account_id_hint,
    )
    if not account_id:
        out["error"] = account_error or "无法识别目标店铺"
        return out
    out["account_id"] = account_id

    if not merchant_code:
        out["error"] = "飞书商品编码为空"
        return out

    already_on_sale_pdd = ""
    try:
        listed_check = check_merchant_code_already_on_sale(
            account_id=account_id,
            merchant_code=merchant_code,
        )
        if listed_check.get("checked") and listed_check.get("listed"):
            already_on_sale_pdd = str(listed_check.get("pdd_product_id") or "").strip()
            # 挂回模式：已在售仍进入限时，不整单跳过
            logger.info(
                "attach retry merchant already on sale, continue limited_time record_id=%s pdd=%s",
                record_id,
                already_on_sale_pdd,
            )
    except Exception as exc:
        logger.warning(
            "attach retry precheck goods list failed record_id=%s error=%s",
            record_id,
            exc,
        )

    if not skip_claim:
        claim_result = try_claim_cycle_relist(
            record_id,
            merchant_code=merchant_code,
            account_name=account_name,
            account_id=account_id,
            config=cfg,
            watch=watch_cfg,
        )
        out["claim"] = claim_result.to_dict()
        if not claim_result.claimed:
            if claim_result.reason == "redis_locked":
                out.update(ok=True, skipped=True, reason="already_claimed")
                return out
            if not claim_result.ok:
                out["error"] = claim_result.error or "占用失败"
                return out

    try:
        started = start_attach_retry_on_source_pipeline(
            source_pipeline_id=source_pipeline_id,
            merchant_code=merchant_code,
            account_id=account_id,
            feishu_record_id=record_id,
            material_source=str(watch_cfg.pipeline_material_source or ""),
            skip_listing_if_on_sale=bool(already_on_sale_pdd),
            already_on_sale_pdd_product_id=already_on_sale_pdd,
        )
    except ValueError as exc:
        out["error"] = str(exc)
        return out
    except Exception as exc:
        logger.exception(
            "attach retry start failed record_id=%s source_pipeline=%s",
            record_id,
            source_pipeline_id,
        )
        out["error"] = str(exc)
        return out

    pipeline_id = str(started.get("pipeline_id") or source_pipeline_id).strip()
    out.update(
        ok=True,
        pipeline_id=pipeline_id,
        source_pipeline_id=source_pipeline_id,
        product_codes=list(started.get("selectors") or [merchant_code]),
        reason=str(started.get("reason") or "attach_retry_started"),
        report_platform=report_platform,
        listing_run_id=str(started.get("listing_run_id") or ""),
        limited_time_run_id=str(started.get("limited_time_run_id") or ""),
        skipped_listing=bool(started.get("skipped_listing")),
        failure_log_attach_retry=started.get("failure_log_attach_retry") or {},
    )
    try:
        from pdd_agent.api.services.daily_cycle_relist_service import (
            record_cycle_relist_pipeline_started,
        )

        record_cycle_relist_pipeline_started(out, trigger_source=trigger_source)
    except Exception:
        logger.warning(
            "record daily attach retry failed pipeline_id=%s record_id=%s",
            pipeline_id,
            record_id,
            exc_info=True,
        )
    return out


def dispatch_attach_retry_queue_task_finished(
    row,
    *,
    agent: str,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    from pdd_agent.api.services.failure_log_attach_retry.policy import (
        dispatch_attach_retry_queue_task_finished as _dispatch,
        is_attach_retry_limited_time_run,
        is_attach_retry_listing_run,
    )

    if not (is_attach_retry_listing_run(row, run_id) or is_attach_retry_limited_time_run(row, run_id)):
        return False
    return _dispatch(
        row,
        agent=agent,
        run_id=run_id,
        success=success,
        result=result,
        error=error,
    )


def maybe_defer_activity_task_execution(row, *, task_id: str, run_id: str) -> bool:
    from pdd_agent.api.services.failure_log_attach_retry.activity_policy import (
        maybe_defer_activity_task_execution as _defer,
    )

    return _defer(row, task_id=task_id, run_id=run_id)


def build_attach_retry_public_state(row) -> dict[str, Any]:
    from pdd_agent.api.services.failure_log_attach_retry.policy import (
        build_attach_retry_public_state as _build,
    )

    return _build(row)


def patch_batch_product_stage(**kwargs) -> dict[str, Any]:
    from pdd_agent.api.services.failure_log_attach_retry.stage_patch import (
        patch_batch_product_stage as _patch,
    )

    return _patch(**kwargs)

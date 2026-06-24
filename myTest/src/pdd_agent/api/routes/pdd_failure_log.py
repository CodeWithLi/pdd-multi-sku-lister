"""飞书发布失败日志读取 API（含流程字段）。"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.pdd_failure_log import (
    PddFailureLogFieldMetaOut,
    PddFailureLogListResponse,
    PddFailureLogRecordOut,
    PddFailureLogWorkflowOut,
)
from pdd_agent.api.schemas.pdd_failure_log_watch import (
    PddFailureCycleRelistActionOut,
    PddFailureCycleRelistCandidateListResponse,
    PddFailureCycleRelistCandidateOut,
    PddFailureCycleRelistClaimIn,
    PddFailureCycleRelistClaimOut,
    PddFailureCycleRelistPollResponse,
    PddFailureCycleRelistReleaseIn,
    PddFailureCycleRelistTriggerIn,
    PddFailureCycleRelistTriggerOut,
    PddFailureCycleRelistWatchOut,
    PddFailureCycleRelistWatchUpdateIn,
)
from pdd_agent.api.services.failure_cycle_relist_scheduler import (
    get_failure_cycle_relist_watch_scheduler,
)
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    load_feishu_config,
    save_pdd_failure_cycle_relist_watch_to_config,
)
from pdd_agent.integrations.feishu.pdd_failure_log_read import list_pdd_failure_logs
from pdd_agent.integrations.feishu.pdd_failure_log_watch import list_cycle_relist_candidates
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim import (
    get_cycle_relist_claim,
    release_cycle_relist_claim,
    try_claim_cycle_relist,
)
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger import (
    process_failure_cycle_relist_candidate,
)

router = APIRouter(prefix="/pdd-failure-logs", tags=["pdd-failure-logs"])


@router.get("", response_model=PddFailureLogListResponse)
def get_pdd_failure_logs(limit: int = Query(100, ge=1, le=500)):
    cfg = load_feishu_config()
    if not cfg.bitable_app_token:
        raise HTTPException(status_code=422, detail="未配置 bitable_app_token")

    try:
        payload = list_pdd_failure_logs(cfg, FeishuClient(cfg), limit=limit)
    except FeishuAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": str(exc),
                "code": exc.code,
                "payload_msg": (exc.payload or {}).get("msg") if isinstance(exc.payload, dict) else "",
            },
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"飞书网络异常: {exc}") from exc

    if not payload.get("ok"):
        return PddFailureLogListResponse(
            ok=False,
            error=str(payload.get("error") or "读取失败"),
            table_name_candidates=list(payload.get("table_name_candidates") or []),
        )

    items = [
        PddFailureLogRecordOut(
            record_id=str(row.get("record_id") or ""),
            date=str(row.get("date") or ""),
            merchant_code=str(row.get("merchant_code") or ""),
            report_platform=str(row.get("report_platform") or ""),
            account_name=str(row.get("account_name") or ""),
            record_type=str(row.get("record_type") or ""),
            failure_reason=str(row.get("failure_reason") or ""),
            publish_start=str(row.get("publish_start") or ""),
            publish_end=str(row.get("publish_end") or ""),
            duration_seconds=str(row.get("duration_seconds") or ""),
            process_completed=PddFailureLogWorkflowOut(**(row.get("process_completed") or {})),
            cycle_relist=str(row.get("cycle_relist") or ""),
            processor=str(row.get("processor") or ""),
            processed_at=str(row.get("processed_at") or ""),
            fields_raw=dict(row.get("fields_raw") or {}),
        )
        for row in payload.get("items") or []
    ]

    field_meta = [
        PddFailureLogFieldMetaOut(**meta)
        for meta in payload.get("field_meta") or []
    ]

    return PddFailureLogListResponse(
        ok=True,
        app_token=str(payload.get("app_token") or ""),
        table_id=str(payload.get("table_id") or ""),
        table_name=str(payload.get("table_name") or ""),
        resolve_method=str(payload.get("resolve_method") or ""),
        mirror_field_name=str(payload.get("mirror_field_name") or ""),
        mirror_api_readable=bool(payload.get("mirror_api_readable")),
        total=int(payload.get("total") or 0),
        items=items,
        field_meta=field_meta,
    )


def _candidate_with_action(
    row: dict,
    *,
    scheduler,
    new_record_ids: set[str] | None = None,
) -> PddFailureCycleRelistCandidateOut:
    rid = str(row.get("record_id") or "")
    action = scheduler.record_actions.get(rid) or {}
    new_ids = new_record_ids or {
        str(x.get("record_id") or "") for x in scheduler.new_items
    }

    action_status = str(action.get("status") or "")
    action_message = str(action.get("message") or "")
    if not action:
        if rid in new_ids:
            action_status = "pending"
            action_message = "本轮新发现，等待自动处理"
        else:
            action_status = "waiting"
            action_message = "已纳入监控，符合条件时会自动跑链路"

    return PddFailureCycleRelistCandidateOut(
        record_id=rid,
        merchant_code=str(row.get("merchant_code") or ""),
        account_name=str(row.get("account_name") or ""),
        report_platform=str(row.get("report_platform") or ""),
        record_type=str(row.get("record_type") or ""),
        failure_reason=str(row.get("failure_reason") or ""),
        process_status=str(row.get("process_status") or ""),
        cycle_relist=str(row.get("cycle_relist") or ""),
        processor=str(row.get("processor") or ""),
        processed_at=str(row.get("processed_at") or ""),
        date=str(row.get("date") or ""),
        action_status=action_status,
        action_message=action_message,
        action_at=str(action.get("at") or ""),
        pipeline_id=str(action.get("pipeline_id") or ""),
    )


def _watch_out() -> PddFailureCycleRelistWatchOut:
    cfg = load_feishu_config()
    watch = cfg.pdd_upload_log.failure_cycle_relist_watch
    scheduler = get_failure_cycle_relist_watch_scheduler()
    recent = [
        PddFailureCycleRelistActionOut(**item)
        for item in scheduler.recent_actions
    ]
    return PddFailureCycleRelistWatchOut(
        enabled=bool(watch.enabled),
        poll_seconds=int(watch.poll_seconds),
        completed_statuses=list(watch.completed_statuses),
        exclude_failure_reason_contains=str(watch.exclude_failure_reason_contains or ""),
        scheduler_running=scheduler.is_running,
        last_poll_at=scheduler.last_poll_at,
        last_error=scheduler.last_error,
        candidate_total=scheduler.candidate_total,
        new_count=len(scheduler.new_items),
        recent_actions=recent,
    )


@router.get("/cycle-relist/watch", response_model=PddFailureCycleRelistWatchOut)
def get_cycle_relist_watch():
    return _watch_out()


@router.put("/cycle-relist/watch", response_model=PddFailureCycleRelistWatchOut)
def update_cycle_relist_watch(body: PddFailureCycleRelistWatchUpdateIn):
    cfg = load_feishu_config()
    watch = cfg.pdd_upload_log.failure_cycle_relist_watch
    auto_on = bool(body.enabled)
    save_pdd_failure_cycle_relist_watch_to_config(
        enabled=body.enabled,
        poll_seconds=body.poll_seconds,
        completed_statuses=list(body.completed_statuses),
        exclude_failure_reason_contains=body.exclude_failure_reason_contains,
        ignore_existing_on_start=False if auto_on else watch.ignore_existing_on_start,
        claim_on_discover=auto_on,
        trigger_pipeline_on_discover=auto_on,
        pipeline_report_platforms=list(watch.pipeline_report_platforms),
        pipeline_activity_ids=list(watch.pipeline_activity_ids),
        pipeline_category_keyword=watch.pipeline_category_keyword,
        pipeline_auto_promotion=watch.pipeline_auto_promotion,
        pipeline_continue_after_limited_time_failure=watch.pipeline_continue_after_limited_time_failure,
        pipeline_continue_after_activity_failure=watch.pipeline_continue_after_activity_failure,
        pipeline_activity_delay_hours=watch.pipeline_activity_delay_hours,
        pipeline_demo_mode=watch.pipeline_demo_mode,
        pipeline_slot_alignment_test=watch.pipeline_slot_alignment_test,
        pipeline_material_source=watch.pipeline_material_source,
    )
    scheduler = get_failure_cycle_relist_watch_scheduler()
    scheduler.reset_tracking()
    if body.enabled:
        scheduler.start()
    return _watch_out()


@router.post("/cycle-relist/poll", response_model=PddFailureCycleRelistPollResponse)
async def poll_cycle_relist_candidates():
    scheduler = get_failure_cycle_relist_watch_scheduler()
    try:
        result = await scheduler.poll_once(force=True)
    except FeishuAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return PddFailureCycleRelistPollResponse(**result)


@router.post("/cycle-relist/claim", response_model=PddFailureCycleRelistClaimOut)
def claim_cycle_relist(body: PddFailureCycleRelistClaimIn):
    cfg = load_feishu_config()
    if not cfg.bitable_app_token:
        raise HTTPException(status_code=422, detail="未配置 bitable_app_token")
    try:
        result = try_claim_cycle_relist(
            body.record_id,
            merchant_code=body.merchant_code,
            account_name=body.account_name,
            config=cfg,
            client=FeishuClient(cfg),
        )
    except FeishuAPIError as exc:
        return PddFailureCycleRelistClaimOut(
            ok=False,
            claimed=False,
            record_id=body.record_id,
            error=str(exc),
        )
    return PddFailureCycleRelistClaimOut(**result.to_dict())


@router.post("/cycle-relist/trigger", response_model=PddFailureCycleRelistTriggerOut)
def trigger_cycle_relist_pipeline(body: PddFailureCycleRelistTriggerIn):
    cfg = load_feishu_config()
    if not cfg.bitable_app_token:
        raise HTTPException(status_code=422, detail="未配置 bitable_app_token")
    outcome = process_failure_cycle_relist_candidate(
        {
            "record_id": body.record_id,
            "merchant_code": body.merchant_code,
            "account_name": body.account_name,
            "report_platform": body.report_platform,
        },
        config=cfg,
    )
    return PddFailureCycleRelistTriggerOut(
        ok=bool(outcome.get("ok")),
        skipped=bool(outcome.get("skipped")),
        reason=str(outcome.get("reason") or ""),
        error=str(outcome.get("error") or ""),
        record_id=str(outcome.get("record_id") or ""),
        merchant_code=str(outcome.get("merchant_code") or ""),
        account_name=str(outcome.get("account_name") or ""),
        account_id=str(outcome.get("account_id") or ""),
        pipeline_id=str(outcome.get("pipeline_id") or ""),
        product_codes=list(outcome.get("product_codes") or []),
        claim=dict(outcome.get("claim") or {}),
    )


@router.post("/cycle-relist/release", response_model=PddFailureCycleRelistClaimOut)
def release_cycle_relist(body: PddFailureCycleRelistReleaseIn):
    cfg = load_feishu_config()
    if not cfg.bitable_app_token:
        raise HTTPException(status_code=422, detail="未配置 bitable_app_token")
    try:
        result = release_cycle_relist_claim(
            body.record_id,
            final_value=body.final_value or None,
            update_feishu=body.update_feishu,
            config=cfg,
            client=FeishuClient(cfg),
        )
    except FeishuAPIError as exc:
        return PddFailureCycleRelistClaimOut(
            ok=False,
            claimed=False,
            record_id=body.record_id,
            error=str(exc),
        )
    return PddFailureCycleRelistClaimOut(**result.to_dict())


@router.get("/cycle-relist/claim/{record_id}", response_model=PddFailureCycleRelistClaimOut)
def get_cycle_relist_claim_status(record_id: str):
    payload = get_cycle_relist_claim(record_id)
    if not payload:
        return PddFailureCycleRelistClaimOut(
            ok=True,
            claimed=False,
            record_id=record_id,
            reason="not_claimed",
        )
    return PddFailureCycleRelistClaimOut(
        ok=True,
        claimed=True,
        record_id=record_id,
        reason="redis_locked",
        placeholder=str(payload.get("placeholder") or ""),
        redis_payload=payload,
    )


@router.get("/cycle-relist/candidates", response_model=PddFailureCycleRelistCandidateListResponse)
def list_cycle_relist_candidates_api(
    only_new: bool = Query(False, description="仅返回本轮新发现的候选"),
):
    cfg = load_feishu_config()
    if not cfg.bitable_app_token:
        raise HTTPException(status_code=422, detail="未配置 bitable_app_token")

    scheduler = get_failure_cycle_relist_watch_scheduler()
    try:
        if only_new:
            if not scheduler.last_poll_at:
                poll = scheduler.poll_sync(force=True)
            else:
                poll = {
                    "new_items": scheduler.new_items,
                    "total": scheduler.candidate_total,
                }
            items = list(poll.get("new_items") or [])
            new_ids = {str(x.get("record_id") or "") for x in items}
            return PddFailureCycleRelistCandidateListResponse(
                ok=True,
                total=len(items),
                items=[
                    _candidate_with_action(row, scheduler=scheduler, new_record_ids=new_ids)
                    for row in items
                ],
                new_items=[
                    _candidate_with_action(row, scheduler=scheduler, new_record_ids=new_ids)
                    for row in items
                ],
            )

        payload = list_cycle_relist_candidates(cfg)
    except FeishuAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not payload.get("ok"):
        return PddFailureCycleRelistCandidateListResponse(
            ok=False,
            error=str(payload.get("error") or "读取失败"),
        )

    items = [
        _candidate_with_action(row, scheduler=scheduler)
        for row in payload.get("items") or []
    ]
    new_rows = [
        _candidate_with_action(row, scheduler=scheduler)
        for row in scheduler.new_items
    ]
    return PddFailureCycleRelistCandidateListResponse(
        ok=True,
        total=int(payload.get("total") or 0),
        items=items,
        new_items=new_rows,
        table_id=str(payload.get("table_id") or ""),
        table_name=str(payload.get("table_name") or ""),
    )

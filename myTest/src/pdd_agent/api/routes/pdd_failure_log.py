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
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import load_feishu_config
from pdd_agent.integrations.feishu.pdd_failure_log_read import list_pdd_failure_logs

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

"""Feishu Bitable CRUD APIs for internal teammates (user token only)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.feishu_bitable import (
    FeishuBitableBatchCreateRecordsIn,
    FeishuBitableBatchDeleteRecordsIn,
    FeishuBitableCopyAppIn,
    FeishuBitableCreateAppIn,
    FeishuBitableCreateFieldIn,
    FeishuBitableCreateTableIn,
    FeishuBitableUpdateFieldIn,
    FeishuBitableUpdateRecordIn,
    FeishuBitableUpdateTableIn,
)
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import load_feishu_config

router = APIRouter(prefix="/feishu-bitable", tags=["feishu-bitable"])


def _client() -> FeishuClient:
    return FeishuClient(load_feishu_config())


def _default_app_token() -> str:
    token = (load_feishu_config().bitable_app_token or "").strip()
    if not token:
        raise HTTPException(status_code=422, detail="未配置 bitable_app_token，且请求未传 app_token")
    return token


def _app_token(text: str) -> str:
    return text.strip() if text and text.strip() else _default_app_token()


def _request(method: str, path: str, *, params=None, json=None) -> dict:
    try:
        return _client().request(
            method,
            path,
            params=params,
            json=json,
            prefer_user_token=True,
        )
    except FeishuAPIError as exc:
        detail = {
            "message": str(exc),
            "code": exc.code,
            "payload_msg": (exc.payload or {}).get("msg") if isinstance(exc.payload, dict) else "",
        }
        raise HTTPException(status_code=502, detail=detail) from exc


@router.get("/health")
def feishu_bitable_health():
    cfg = load_feishu_config()
    return {
        "ok": True,
        "auth_mode": "user_access_token",
        "configured": bool(cfg.app_id and cfg.app_secret),
        "default_app_token": cfg.bitable_app_token,
        "default_table_id": cfg.table_id,
        "default_table_name": cfg.table_name,
        "user_token_ready": bool(cfg.user_access_token),
    }


@router.post("/apps")
def create_bitable_app(body: FeishuBitableCreateAppIn):
    payload = {"name": body.name}
    if body.folder_token.strip():
        payload["folder_token"] = body.folder_token.strip()
    if body.time_zone.strip():
        payload["time_zone"] = body.time_zone.strip()
    return _request("POST", "/bitable/v1/apps", json=payload)


@router.post("/apps/copy")
def copy_bitable_app(body: FeishuBitableCopyAppIn):
    source_app_token = body.source_app_token.strip()
    if not source_app_token:
        raise HTTPException(status_code=422, detail="source_app_token 不能为空")
    payload: dict[str, object] = {"without_content": bool(body.without_content)}
    if body.name.strip():
        payload["name"] = body.name.strip()
    if body.folder_token.strip():
        payload["folder_token"] = body.folder_token.strip()
    if body.time_zone.strip():
        payload["time_zone"] = body.time_zone.strip()
    return _request("POST", f"/bitable/v1/apps/{source_app_token}/copy", json=payload)


@router.get("/tables")
def list_tables(app_token: str = Query(default="")):
    token = _app_token(app_token)
    return _request(
        "GET",
        f"/bitable/v1/apps/{token}/tables",
        params={"page_size": 100},
    )


@router.post("/tables")
def create_table(body: FeishuBitableCreateTableIn):
    token = _app_token(body.app_token)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name 不能为空")
    return _request(
        "POST",
        f"/bitable/v1/apps/{token}/tables",
        json={"table": {"name": name}},
    )


@router.patch("/tables/{table_id}")
def update_table(table_id: str, body: FeishuBitableUpdateTableIn):
    token = _app_token(body.app_token)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name 不能为空")
    return _request(
        "PATCH",
        f"/bitable/v1/apps/{token}/tables/{table_id}",
        json={"name": name},
    )


@router.delete("/tables/{table_id}")
def delete_table(
    table_id: str,
    app_token: str = Query(default=""),
):
    token = _app_token(app_token)
    return _request("DELETE", f"/bitable/v1/apps/{token}/tables/{table_id}")


@router.get("/tables/{table_id}/fields")
def list_fields(
    table_id: str,
    app_token: str = Query(default=""),
):
    token = _app_token(app_token)
    return _request(
        "GET",
        f"/bitable/v1/apps/{token}/tables/{table_id}/fields",
        params={"page_size": 100},
    )


@router.post("/fields")
def create_field(body: FeishuBitableCreateFieldIn):
    token = _app_token(body.app_token)
    payload = {"field_name": body.field_name.strip(), "type": int(body.type)}
    if body.property is not None:
        payload["property"] = body.property
    return _request(
        "POST",
        f"/bitable/v1/apps/{token}/tables/{body.table_id}/fields",
        json=payload,
    )


@router.put("/fields/{field_id}")
def update_field(field_id: str, body: FeishuBitableUpdateFieldIn):
    token = _app_token(body.app_token)
    payload = {"field_name": body.field_name.strip(), "type": int(body.type)}
    if body.property is not None:
        payload["property"] = body.property
    return _request(
        "PUT",
        f"/bitable/v1/apps/{token}/tables/{body.table_id}/fields/{field_id}",
        json=payload,
    )


@router.delete("/fields/{field_id}")
def delete_field(
    field_id: str,
    table_id: str,
    app_token: str = Query(default=""),
):
    token = _app_token(app_token)
    return _request(
        "DELETE",
        f"/bitable/v1/apps/{token}/tables/{table_id}/fields/{field_id}",
    )


@router.get("/tables/{table_id}/records")
def list_records(
    table_id: str,
    app_token: str = Query(default=""),
    page_size: int = Query(default=100, ge=1, le=500),
    page_token: str = Query(default=""),
):
    token = _app_token(app_token)
    params = {"page_size": page_size}
    if page_token.strip():
        params["page_token"] = page_token.strip()
    return _request(
        "GET",
        f"/bitable/v1/apps/{token}/tables/{table_id}/records",
        params=params,
    )


@router.post("/records/batch-create")
def batch_create_records(body: FeishuBitableBatchCreateRecordsIn):
    token = _app_token(body.app_token)
    if not body.records:
        raise HTTPException(status_code=422, detail="records 不能为空")
    return _request(
        "POST",
        f"/bitable/v1/apps/{token}/tables/{body.table_id}/records/batch_create",
        json={"records": [{"fields": item} for item in body.records]},
    )


@router.put("/records/{record_id}")
def update_record(record_id: str, body: FeishuBitableUpdateRecordIn):
    token = _app_token(body.app_token)
    return _request(
        "PUT",
        f"/bitable/v1/apps/{token}/tables/{body.table_id}/records/{record_id}",
        json={"fields": body.fields},
    )


@router.post("/records/batch-delete")
def batch_delete_records(body: FeishuBitableBatchDeleteRecordsIn):
    token = _app_token(body.app_token)
    ids = [x.strip() for x in body.record_ids if x.strip()]
    if not ids:
        raise HTTPException(status_code=422, detail="record_ids 不能为空")
    return _request(
        "POST",
        f"/bitable/v1/apps/{token}/tables/{body.table_id}/records/batch_delete",
        json={"records": ids},
    )

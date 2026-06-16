"""飞书集成测试 API（独立挂载，不进入主 app.py）。"""

from __future__ import annotations

from datetime import datetime
import secrets

from fastapi import APIRouter, HTTPException

from pdd_agent.integrations.feishu.bitable import list_tables
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    DEFAULT_FEISHU_CONFIG_PATH,
    load_feishu_config,
    save_oauth_tokens_to_config,
)
from pdd_agent.integrations.feishu.listing_log import (
    LISTING_LOG_TABLE_NAME,
    ensure_listing_log_table,
    list_published_products_for_date,
    sync_listing_log_for_date,
)
from pdd_agent.integrations.feishu.schemas import (
    FeishuCheckResult,
    FeishuConfigOut,
    FeishuInitTableResult,
    FeishuOAuthAuthorizeResult,
    FeishuOAuthExchangeRequest,
    FeishuOAuthExchangeResult,
    FeishuPreviewItem,
    FeishuPreviewResult,
    FeishuSyncRequest,
)

router = APIRouter(prefix="/feishu", tags=["feishu-test"])
_oauth_states: set[str] = set()


def _mask_secret(secret: str) -> str:
    text = str(secret or "")
    if len(text) <= 4:
        return "****" if text else ""
    return text[:4] + "****"


@router.get("/health")
def feishu_health():
    return {"service": "feishu-test-api", "ok": True}


@router.get("/config", response_model=FeishuConfigOut)
def feishu_config():
    cfg = load_feishu_config()
    names = cfg.field_names
    return FeishuConfigOut(
        config_path=str(DEFAULT_FEISHU_CONFIG_PATH),
        app_id=cfg.app_id,
        app_secret_masked=_mask_secret(cfg.app_secret),
        oauth_redirect_uri=cfg.oauth_redirect_uri,
        oauth_scope=cfg.oauth_scope,
        use_user_access_token=cfg.use_user_access_token,
        user_token_ready=bool(cfg.user_access_token),
        bitable_app_token=cfg.bitable_app_token,
        table_id=cfg.table_id,
        table_name=cfg.table_name or LISTING_LOG_TABLE_NAME,
        dedupe_field=cfg.dedupe_field,
        field_names=names.model_dump(),
    )


@router.get("/oauth/authorize-url", response_model=FeishuOAuthAuthorizeResult)
def feishu_oauth_authorize_url():
    cfg = load_feishu_config()
    if not cfg.app_id or not cfg.app_secret:
        raise HTTPException(status_code=422, detail="未配置 app_id / app_secret")
    state = secrets.token_urlsafe(24)
    _oauth_states.add(state)
    client = FeishuClient(cfg)
    url = client.build_oauth_authorize_url(state=state)
    return FeishuOAuthAuthorizeResult(
        authorize_url=url,
        state=state,
        scope=cfg.oauth_scope,
        redirect_uri=cfg.oauth_redirect_uri,
    )


@router.post("/oauth/exchange-code", response_model=FeishuOAuthExchangeResult)
def feishu_oauth_exchange_code(body: FeishuOAuthExchangeRequest):
    cfg = load_feishu_config()
    if body.state and body.state not in _oauth_states:
        raise HTTPException(status_code=422, detail="state 不匹配，请重新生成授权链接")
    try:
        client = FeishuClient(cfg)
        data = client.exchange_code_for_user_access_token(
            code=body.code.strip(),
            redirect_uri=body.redirect_uri.strip() or None,
        )
        save_oauth_tokens_to_config(
            user_access_token=str(data.get("access_token") or ""),
            expires_in=int(data.get("expires_in") or 0),
            refresh_token=str(data.get("refresh_token") or ""),
            refresh_token_expires_in=int(data.get("refresh_token_expires_in") or 0),
        )
        if body.state:
            _oauth_states.discard(body.state)
        return FeishuOAuthExchangeResult(
            ok=True,
            message="user_access_token 获取成功，已写入 feishu.yaml",
            access_token_length=len(str(data.get("access_token") or "")),
            expires_in=int(data.get("expires_in") or 0),
            refresh_token_present=bool(data.get("refresh_token")),
        )
    except FeishuAPIError as exc:
        return FeishuOAuthExchangeResult(ok=False, message=str(exc))


@router.get("/tables")
def feishu_tables():
    """列出 Base 下所有数据表（调试用）。"""
    cfg = load_feishu_config()
    if not cfg.bitable_app_token:
        raise HTTPException(status_code=422, detail="未配置 bitable_app_token")
    try:
        client = FeishuClient(cfg)
        items = list_tables(client, cfg.bitable_app_token)
        return {
            "count": len(items),
            "items": [
                {"table_id": item.get("table_id"), "name": item.get("name")}
                for item in items
            ],
        }
    except FeishuAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/check", response_model=FeishuCheckResult)
def feishu_check():
    cfg = load_feishu_config()
    if not cfg.app_id or not cfg.app_secret:
        return FeishuCheckResult(
            ok=False,
            message="缺少 app_id / app_secret，请配置 config/feishu.yaml",
            auth_mode="user_access_token",
        )
    if cfg.use_user_access_token and not cfg.user_access_token:
        return FeishuCheckResult(
            ok=False,
            message="当前启用 user_access_token，但尚未授权。请先执行 OAuth 授权并交换 code。",
            auth_mode="user_access_token",
        )
    try:
        client = FeishuClient(cfg)
        token = client.get_user_access_token() if cfg.use_user_access_token else client.get_tenant_access_token()
        return FeishuCheckResult(
            ok=True,
            message="access_token 可用",
            token_length=len(token),
            auth_mode="user_access_token" if cfg.use_user_access_token else "tenant_access_token",
        )
    except FeishuAPIError as exc:
        return FeishuCheckResult(
            ok=False,
            message=str(exc),
            auth_mode="user_access_token" if cfg.use_user_access_token else "tenant_access_token",
        )


@router.post("/init-table", response_model=FeishuInitTableResult)
def feishu_init_table():
    try:
        table_id = ensure_listing_log_table()
        cfg = load_feishu_config()
        return FeishuInitTableResult(
            table_name=cfg.table_name or LISTING_LOG_TABLE_NAME,
            table_id=table_id,
            message="表与字段已就绪；若 table_id 为空已写回 feishu.yaml",
        )
    except FeishuAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/preview", response_model=FeishuPreviewResult)
def feishu_preview(date: str):
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date 格式须为 YYYY-MM-DD") from exc
    try:
        rows = list_published_products_for_date(day)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    items = [
        FeishuPreviewItem(
            mapping_id=r.mapping_id,
            account_id=r.account_id,
            product_code=r.product_code,
            listing_label=r.listing_label,
            pdd_product_id=r.pdd_product_id,
            published_at=(r.published_at or r.created_at).isoformat()
            if (r.published_at or r.created_at)
            else "",
        )
        for r in rows
    ]
    return FeishuPreviewResult(date=day.isoformat(), count=len(items), items=items)


@router.post("/sync")
def feishu_sync(body: FeishuSyncRequest):
    try:
        day = datetime.strptime(body.date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date 格式须为 YYYY-MM-DD") from exc
    try:
        return sync_listing_log_for_date(
            day,
            dry_run=body.dry_run,
            minimal_fields=body.minimal_fields,
        )
    except FeishuAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

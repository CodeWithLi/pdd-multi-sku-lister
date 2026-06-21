"""主 API 飞书 OAuth（侧边栏手动授权；回调由后端 8010 接收）。"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from pdd_agent.integrations.feishu.bitable import list_tables
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import load_feishu_config, save_oauth_tokens_to_config
from pdd_agent.integrations.feishu.schemas import (
    FeishuOAuthAuthorizeResult,
    FeishuOAuthExchangeRequest,
    FeishuOAuthExchangeResult,
)

router = APIRouter(prefix="/feishu/oauth", tags=["feishu-oauth"])
_oauth_states: set[str] = set()
_FRONTEND_HOME = "http://localhost:5173/"


def _oauth_result_html(*, ok: bool, title: str, message: str) -> str:
    color = "#16a34a" if ok else "#dc2626"
    icon = "✓" if ok else "✕"
    extra = (
        f'<p style="margin-top:16px"><a href="{_FRONTEND_HOME}">返回拼多多上架助手</a></p>'
        if ok
        else (
            f'<p style="margin-top:16px;color:#64748b">请回到前端侧边栏重新点击「去授权」。</p>'
            f'<p><a href="{_FRONTEND_HOME}">打开前端</a></p>'
        )
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:system-ui,sans-serif;max-width:520px;margin:48px auto;padding:0 16px;color:#0f172a">
  <div style="border:1px solid #e2e8f0;border-radius:12px;padding:24px">
    <div style="font-size:32px;color:{color}">{icon}</div>
    <h1 style="font-size:20px;margin:12px 0 8px">{title}</h1>
    <p style="color:#475569;line-height:1.6;margin:0">{message}</p>
    {extra}
  </div>
</body></html>"""


class FeishuOAuthStatusResult(BaseModel):
    authorized: bool
    message: str = ""
    need_oauth: bool = False
    redirect_uri: str = ""


@router.get("/status", response_model=FeishuOAuthStatusResult)
def feishu_oauth_status():
    """检测 user_access_token 是否可用（会尝试刷新并访问多维表格）。"""
    cfg = load_feishu_config()
    if not cfg.use_user_access_token:
        return FeishuOAuthStatusResult(
            authorized=True,
            message="未启用 user_access_token，无需 OAuth",
            need_oauth=False,
        )
    if not cfg.app_id or not cfg.app_secret:
        return FeishuOAuthStatusResult(
            authorized=False,
            message="未配置飞书 app_id / app_secret",
            need_oauth=False,
        )
    if not str(cfg.user_access_token or "").strip() and not str(cfg.refresh_token or "").strip():
        return FeishuOAuthStatusResult(
            authorized=False,
            message="尚未完成飞书授权",
            need_oauth=True,
            redirect_uri=cfg.oauth_redirect_uri,
        )
    try:
        client = FeishuClient(cfg)
        if str(cfg.bitable_app_token or "").strip():
            list_tables(client, cfg.bitable_app_token)
        else:
            client.get_user_access_token()
        return FeishuOAuthStatusResult(authorized=True, message="飞书授权有效")
    except FeishuAPIError as exc:
        msg = str(exc)
        need = any(token in msg for token in ("OAuth", "refresh_token", "user_access_token", "授权"))
        return FeishuOAuthStatusResult(
            authorized=False,
            message=msg,
            need_oauth=need or True,
            redirect_uri=cfg.oauth_redirect_uri,
        )


@router.get("/authorize-url", response_model=FeishuOAuthAuthorizeResult)
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


class FeishuOAuthExchangeBody(BaseModel):
    code: str = Field(..., min_length=1)
    state: str = ""
    redirect_uri: str = ""


@router.get("/callback", response_class=HTMLResponse)
def feishu_oauth_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
):
    """飞书 OAuth 浏览器回调（走 8010，不依赖 Vite 5173 是否在线）。"""
    if error:
        detail = error_description or error
        return HTMLResponse(
            _oauth_result_html(ok=False, title="飞书授权失败", message=detail),
            status_code=400,
        )
    code = code.strip()
    state = state.strip()
    if not code:
        return HTMLResponse(
            _oauth_result_html(ok=False, title="飞书授权失败", message="回调缺少 code 参数"),
            status_code=400,
        )
    if state and state not in _oauth_states:
        return HTMLResponse(
            _oauth_result_html(
                ok=False,
                title="飞书授权失败",
                message="state 不匹配或已过期，请重新发起授权",
            ),
            status_code=422,
        )
    cfg = load_feishu_config()
    try:
        client = FeishuClient(cfg)
        data = client.exchange_code_for_user_access_token(code=code)
        save_oauth_tokens_to_config(
            user_access_token=str(data.get("access_token") or ""),
            expires_in=int(data.get("expires_in") or 0),
            refresh_token=str(data.get("refresh_token") or ""),
            refresh_token_expires_in=int(data.get("refresh_token_expires_in") or 0),
        )
        if state:
            _oauth_states.discard(state)
        return HTMLResponse(
            _oauth_result_html(
                ok=True,
                title="飞书授权成功",
                message="token 已写入 feishu.yaml，可返回前端继续使用。建议重启后端以初始化飞书日志表。",
            )
        )
    except FeishuAPIError as exc:
        return HTMLResponse(
            _oauth_result_html(ok=False, title="飞书授权失败", message=str(exc)),
            status_code=502,
        )


@router.post("/exchange-code", response_model=FeishuOAuthExchangeResult)
def feishu_oauth_exchange_code(body: FeishuOAuthExchangeBody):
    cfg = load_feishu_config()
    if body.state and body.state not in _oauth_states:
        raise HTTPException(status_code=422, detail="state 不匹配，请重新发起授权")
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
            message="飞书授权成功，token 已写入 feishu.yaml",
            access_token_length=len(str(data.get("access_token") or "")),
            expires_in=int(data.get("expires_in") or 0),
            refresh_token_present=bool(data.get("refresh_token")),
        )
    except FeishuAPIError as exc:
        return FeishuOAuthExchangeResult(ok=False, message=str(exc))

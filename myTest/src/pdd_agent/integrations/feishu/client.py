"""飞书 Open API 轻量客户端（tenant_access_token + 通用请求）。"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

import httpx

from pdd_agent.integrations.feishu.config import FeishuConfig

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
FEISHU_OAUTH_AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRYABLE = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
)


class FeishuAPIError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload


_USER_TOKEN_EXPIRED_CODES = frozenset({99991663, 99991668, 99991677})
_BITABLE_RETRYABLE_CODES = frozenset({1254607, 1255040, 1254290, 1254291})
_BITABLE_RETRY_BACKOFF_SECONDS = (0.5, 1.2, 2.5)


class FeishuClient:
    def __init__(self, config: FeishuConfig, *, timeout: float = 60.0) -> None:
        self._config = config
        self._timeout = timeout
        self._token: str = ""
        self._token_expire_at: float = 0.0
        self._user_token: str = str(config.user_access_token or "")
        self._user_token_expire_at: float = float(config.user_access_token_expires_at or 0)

    def _ensure_config(self) -> None:
        if not self._config.app_id or not self._config.app_secret:
            raise FeishuAPIError("缺少飞书 app_id / app_secret，请配置 config/feishu.yaml 或 .env")
        if not self._config.bitable_app_token:
            raise FeishuAPIError("缺少 bitable_app_token（多维表格 Base 的 app_token）")

    def get_tenant_access_token(self, *, force_refresh: bool = False) -> str:
        self._ensure_config()
        now = time.time()
        if self._token and now < self._token_expire_at - 60 and not force_refresh:
            return self._token

        url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
        body = {"app_id": self._config.app_id, "app_secret": self._config.app_secret}
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()

        if int(data.get("code", -1)) != 0:
            raise FeishuAPIError(
                f"获取 tenant_access_token 失败: {data.get('msg')}",
                code=int(data.get("code", -1)),
                payload=data,
            )

        self._token = str(data["tenant_access_token"])
        self._token_expire_at = now + int(data.get("expire", 7200))
        return self._token

    def build_oauth_authorize_url(self, *, state: str, scope: str | None = None) -> str:
        self._ensure_config()
        redirect_uri = (self._config.oauth_redirect_uri or "").strip()
        if not redirect_uri:
            raise FeishuAPIError("缺少 oauth_redirect_uri，请先配置 config/feishu.yaml")
        query = {
            "client_id": self._config.app_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": (scope or self._config.oauth_scope or "").strip(),
            "state": state,
            "prompt": "consent",
        }
        return f"{FEISHU_OAUTH_AUTHORIZE_URL}?{urlencode(query)}"

    def exchange_code_for_user_access_token(
        self,
        *,
        code: str,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_config()
        if not code:
            raise FeishuAPIError("缺少授权码 code")
        url = f"{FEISHU_API_BASE}/authen/v2/oauth/token"
        body: dict[str, Any] = {
            "grant_type": "authorization_code",
            "client_id": self._config.app_id,
            "client_secret": self._config.app_secret,
            "code": code,
        }
        uri = (redirect_uri or self._config.oauth_redirect_uri or "").strip()
        if uri:
            body["redirect_uri"] = uri
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, json=body)
            data = resp.json()
        if int(data.get("code", -1)) != 0:
            raise FeishuAPIError(
                f"获取 user_access_token 失败: {data.get('error_description') or data.get('msg') or data.get('error')}",
                code=int(data.get("code", -1)),
                payload=data,
            )
        self._user_token = str(data.get("access_token") or "")
        self._user_token_expire_at = time.time() + int(data.get("expires_in", 0))
        return data

    def _apply_user_token_payload(self, data: dict[str, Any]) -> str:
        from pdd_agent.integrations.feishu.config import save_oauth_tokens_to_config

        token = str(data.get("access_token") or "")
        if not token:
            raise FeishuAPIError("刷新 user_access_token 失败：响应缺少 access_token", payload=data)

        expires_in = int(data.get("expires_in", 0))
        refresh_token = str(data.get("refresh_token") or self._config.refresh_token or "")
        refresh_expires_in = int(data.get("refresh_token_expires_in") or 0)
        now = time.time()

        save_oauth_tokens_to_config(
            user_access_token=token,
            expires_in=expires_in,
            refresh_token=refresh_token,
            refresh_token_expires_in=refresh_expires_in,
        )

        self._user_token = token
        self._user_token_expire_at = now + expires_in
        self._config.user_access_token = token
        self._config.user_access_token_expires_at = int(now + expires_in)
        if refresh_token:
            self._config.refresh_token = refresh_token
        if refresh_expires_in:
            self._config.refresh_token_expires_at = int(now + refresh_expires_in)
        return token

    def refresh_user_access_token(self) -> str:
        self._ensure_config()
        refresh_token = str(self._config.refresh_token or "").strip()
        if not refresh_token:
            raise FeishuAPIError("缺少 refresh_token，请重新 OAuth 授权")

        refresh_expire_at = float(self._config.refresh_token_expires_at or 0)
        if refresh_expire_at and time.time() >= refresh_expire_at - 60:
            raise FeishuAPIError("refresh_token 已过期，请重新 OAuth 授权")

        url = f"{FEISHU_API_BASE}/authen/v2/oauth/token"
        body = {
            "grant_type": "refresh_token",
            "client_id": self._config.app_id,
            "client_secret": self._config.app_secret,
            "refresh_token": refresh_token,
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, json=body)
            data = resp.json()
        if int(data.get("code", -1)) != 0:
            raise FeishuAPIError(
                f"刷新 user_access_token 失败: {data.get('error_description') or data.get('msg') or data.get('error')}",
                code=int(data.get("code", -1)),
                payload=data,
            )
        return self._apply_user_token_payload(data)

    def get_user_access_token(self, *, allow_refresh: bool = True) -> str:
        now = time.time()
        if self._user_token and now < self._user_token_expire_at - 60:
            return self._user_token

        cfg_token = str(self._config.user_access_token or "")
        cfg_expire_at = float(self._config.user_access_token_expires_at or 0)
        if cfg_token and cfg_expire_at and now < cfg_expire_at - 60:
            self._user_token = cfg_token
            self._user_token_expire_at = cfg_expire_at
            return cfg_token

        if allow_refresh and str(self._config.refresh_token or "").strip():
            try:
                return self.refresh_user_access_token()
            except FeishuAPIError:
                if cfg_token:
                    return cfg_token
                raise

        if cfg_token:
            return cfg_token
        raise FeishuAPIError(
            "未配置 user_access_token，请先在测试页完成 OAuth 授权并交换 code",
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        retry_on_token: bool = True,
        prefer_user_token: bool | None = None,
        _bitable_attempt: int = 0,
    ) -> dict[str, Any]:
        use_user_token = self._config.use_user_access_token if prefer_user_token is None else prefer_user_token
        token = self.get_user_access_token() if use_user_token else self.get_tenant_access_token()
        url = path if path.startswith("http") else f"{FEISHU_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {token}"}

        last_network_error: Exception | None = None
        for attempt in range(_NETWORK_RETRY_ATTEMPTS):
            try:
                with httpx.Client(timeout=self._timeout, trust_env=True) as client:
                    resp = client.request(method, url, headers=headers, params=params, json=json)
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise FeishuAPIError(
                        f"飞书 API 返回非 JSON 响应: HTTP {resp.status_code}",
                        payload={"status_code": resp.status_code, "text": resp.text[:200]},
                    ) from exc
                status_code = resp.status_code
                break
            except _NETWORK_RETRYABLE as exc:
                last_network_error = exc
                if attempt + 1 >= _NETWORK_RETRY_ATTEMPTS:
                    raise FeishuAPIError(
                        f"飞书网络连接失败（已重试 {_NETWORK_RETRY_ATTEMPTS} 次）: {exc}",
                        payload={"error": str(exc)},
                    ) from exc
                time.sleep(0.6 * (attempt + 1))
        else:
            raise FeishuAPIError(
                f"飞书网络连接失败: {last_network_error}",
                payload={"error": str(last_network_error)},
            )

        code = int(data.get("code", -1))
        if code in _USER_TOKEN_EXPIRED_CODES and retry_on_token:
            if use_user_token:
                try:
                    self.refresh_user_access_token()
                except FeishuAPIError as exc:
                    raise FeishuAPIError(
                        "user_access_token 失效且自动刷新失败，请重新 OAuth 授权",
                        code=code,
                        payload=data,
                    ) from exc
                return self.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    retry_on_token=False,
                    prefer_user_token=use_user_token,
                )
            self.get_tenant_access_token(force_refresh=True)
            return self.request(
                method,
                path,
                params=params,
                json=json,
                retry_on_token=False,
                prefer_user_token=use_user_token,
            )

        if code != 0:
            if (
                code in _BITABLE_RETRYABLE_CODES
                and _bitable_attempt < len(_BITABLE_RETRY_BACKOFF_SECONDS)
            ):
                time.sleep(_BITABLE_RETRY_BACKOFF_SECONDS[_bitable_attempt])
                return self.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    retry_on_token=retry_on_token,
                    prefer_user_token=use_user_token,
                    _bitable_attempt=_bitable_attempt + 1,
                )
            raise FeishuAPIError(
                f"飞书 API 错误: {data.get('msg')} (code={code})",
                code=code,
                payload=data,
            )
        if status_code >= 400:
            raise FeishuAPIError(
                f"飞书 HTTP 错误: HTTP {status_code}",
                code=code,
                payload=data,
            )
        return data

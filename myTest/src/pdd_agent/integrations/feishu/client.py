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
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
)


class FeishuAPIError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload


class FeishuClient:
    def __init__(self, config: FeishuConfig, *, timeout: float = 30.0) -> None:
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

    def get_user_access_token(self) -> str:
        now = time.time()
        if self._user_token and now < self._user_token_expire_at - 60:
            return self._user_token
        fallback = str(self._config.user_access_token or "")
        if fallback:
            return fallback
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
        if code in {99991663, 99991668} and retry_on_token:
            if use_user_token:
                raise FeishuAPIError(
                    "user_access_token 失效，请重新 OAuth 授权",
                    code=code,
                    payload=data,
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

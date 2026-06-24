"""Alist 上传客户端（生产路径：Alist -> MinIO -> RabbitMQ 自动通知）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.config import AlistConfig, MinioConfig, load_minio_config

logger = get_logger(__name__)


class AlistAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlistUploadResult:
    object_key: str
    virtual_path: str


def alist_configured(config: MinioConfig | None = None) -> bool:
    cfg = config or load_minio_config()
    alist = cfg.alist
    return bool(alist.enabled and alist.url and alist.username and alist.password and alist.root_path)


def alist_virtual_path(object_key: str, *, config: MinioConfig | None = None) -> str:
    """MinIO object key -> Alist 虚拟路径。"""
    cfg = config or load_minio_config()
    root = str(cfg.alist.root_path or "").strip().rstrip("/")
    key = str(object_key or "").strip().lstrip("/")
    if not root or not key:
        raise ValueError("object_key 与 alist.root_path 均不能为空")
    return f"{root}/{key}"


def alist_object_key(virtual_path: str, *, config: MinioConfig | None = None) -> str:
    """Alist 虚拟路径 -> MinIO object key。"""
    cfg = config or load_minio_config()
    root = str(cfg.alist.root_path or "").strip().rstrip("/")
    path = str(virtual_path or "").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    prefix = f"{root}/"
    if not path.startswith(prefix):
        raise ValueError(f"Alist 路径不在 root_path 下: {virtual_path}")
    return path[len(prefix) :].lstrip("/")


def _alist_api_base(config: MinioConfig) -> str:
    base = str(config.alist.url or "").strip().rstrip("/")
    if not base:
        raise AlistAPIError("Alist 未配置 url")
    return base


def _alist_client(config: MinioConfig) -> httpx.Client:
    alist = config.alist
    return httpx.Client(
        base_url=_alist_api_base(config),
        follow_redirects=True,
        timeout=alist.timeout_seconds,
        verify=bool(alist.verify_ssl),
    )


def _alist_request_json(response: httpx.Response, *, action: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AlistAPIError(f"Alist {action} 返回非 JSON: HTTP {response.status_code}") from exc
    if not isinstance(payload, dict):
        raise AlistAPIError(f"Alist {action} 返回格式异常")
    code = payload.get("code")
    if code != 200:
        message = str(payload.get("message") or "unknown error")
        raise AlistAPIError(f"Alist {action} 失败: {message}")
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def delete_alist_path(
    virtual_path: str,
    *,
    token: str | None = None,
    config: MinioConfig | None = None,
) -> None:
    """删除 Alist 文件或目录（与 MinIO 挂载路径对应）。"""
    cfg = config or load_minio_config()
    if not alist_configured(cfg):
        raise AlistAPIError("Alist 未配置")
    path = str(virtual_path or "").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    if path.endswith("/"):
        path = path.rstrip("/")
    if "/" not in path.strip("/"):
        raise AlistAPIError(f"无效的 Alist 路径: {virtual_path}")
    parent, name = path.rsplit("/", 1)
    if not name:
        raise AlistAPIError(f"无效的 Alist 路径: {virtual_path}")
    auth = token or login_alist(config=cfg)
    with _alist_client(cfg) as client:
        response = client.post(
            "/api/fs/remove",
            headers={"Authorization": auth},
            json={"dir": parent, "names": [name]},
        )
        _alist_request_json(response, action="删除")
    logger.info("alist deleted virtual_path=%s", path)


def refresh_alist_path(
    virtual_path: str,
    *,
    token: str | None = None,
    config: MinioConfig | None = None,
) -> None:
    """刷新 Alist 目录缓存（删除 MinIO 对象后让 Alist 重新读取存储）。"""
    cfg = config or load_minio_config()
    if not alist_configured(cfg):
        return
    path = str(virtual_path or "").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    auth = token or login_alist(config=cfg)
    with _alist_client(cfg) as client:
        response = client.post(
            "/api/fs/list",
            headers={"Authorization": auth},
            json={"path": path, "page": 1, "per_page": 1, "refresh": True},
        )
        _alist_request_json(response, action="刷新目录")


def list_alist_entries(
    virtual_path: str,
    *,
    token: str | None = None,
    config: MinioConfig | None = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """列出 Alist 目录内容（可选 refresh 绕过缓存）。"""
    cfg = config or load_minio_config()
    if not alist_configured(cfg):
        return []
    path = str(virtual_path or "").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    auth = token or login_alist(config=cfg)
    with _alist_client(cfg) as client:
        response = client.post(
            "/api/fs/list",
            headers={"Authorization": auth},
            json={"path": path, "page": 1, "per_page": 500, "refresh": bool(refresh)},
        )
        data = _alist_request_json(response, action="列目录")
        content = data.get("content")
        return content if isinstance(content, list) else []


def delete_alist_path_if_empty(
    virtual_path: str,
    *,
    token: str | None = None,
    config: MinioConfig | None = None,
) -> bool:
    """若 Alist 目录为空则删除（用于清理只剩元数据的父文件夹）。"""
    cfg = config or load_minio_config()
    if not alist_configured(cfg):
        return False
    auth = token or login_alist(config=cfg)
    path = str(virtual_path or "").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    refresh_alist_path(path, token=auth, config=cfg)
    entries = list_alist_entries(path, token=auth, config=cfg, refresh=True)
    if entries:
        return False
    try:
        delete_alist_path(path, token=auth, config=cfg)
        return True
    except AlistAPIError:
        return False


def login_alist(*, config: MinioConfig | None = None) -> str:
    cfg = config or load_minio_config()
    if not alist_configured(cfg):
        raise AlistAPIError("Alist 未配置：请填写 config/minio.yaml 的 alist 段")
    with _alist_client(cfg) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": cfg.alist.username, "password": cfg.alist.password},
        )
        data = _alist_request_json(response, action="登录")
        token = str(data.get("token") or "").strip()
        if not token:
            raise AlistAPIError("Alist 登录成功但未返回 token")
        return token


def ensure_alist_directory(virtual_dir: str, *, token: str, config: MinioConfig | None = None) -> None:
    cfg = config or load_minio_config()
    path = str(virtual_dir or "").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    with _alist_client(cfg) as client:
        response = client.post(
            "/api/fs/mkdir",
            headers={"Authorization": token},
            json={"path": path},
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise AlistAPIError("Alist 创建目录返回格式异常")
        code = payload.get("code")
        if code not in {200, 400}:
            message = str(payload.get("message") or "unknown error")
            raise AlistAPIError(f"Alist 创建目录失败: {message}")


def upload_bytes_via_alist(
    object_key: str,
    data: bytes,
    *,
    content_type: str = "image/jpeg",
    token: str | None = None,
    config: MinioConfig | None = None,
) -> AlistUploadResult:
    """经 Alist 上传单文件；MinIO 存储后由服务端通知进 RabbitMQ。"""
    cfg = config or load_minio_config()
    if not alist_configured(cfg):
        raise AlistAPIError("Alist 未配置")
    auth = token or login_alist(config=cfg)
    virtual_path = alist_virtual_path(object_key, config=cfg)
    virtual_dir = virtual_path.rsplit("/", 1)[0]
    ensure_alist_directory(virtual_dir, token=auth, config=cfg)

    encoded_path = quote(virtual_path, safe="")
    headers = {
        "Authorization": auth,
        "File-Path": encoded_path,
        "Content-Type": content_type,
        "Content-Length": str(len(data)),
    }
    with _alist_client(cfg) as client:
        response = client.put("/api/fs/put", headers=headers, content=data)
        _alist_request_json(response, action="上传")
    logger.info("alist uploaded virtual_path=%s object_key=%s", virtual_path, object_key)
    return AlistUploadResult(object_key=object_key, virtual_path=virtual_path)


def check_alist_health(*, config: MinioConfig | None = None) -> dict[str, Any]:
    cfg = config or load_minio_config()
    alist = cfg.alist
    base = {
        "configured": alist_configured(cfg),
        "enabled": bool(alist.enabled),
        "url": alist.url,
        "root_path": alist.root_path,
    }
    if not alist_configured(cfg):
        return {**base, "available": False, "error": "Alist 未配置"}
    try:
        token = login_alist(config=cfg)
        with _alist_client(cfg) as client:
            response = client.post(
                "/api/fs/list",
                headers={"Authorization": token},
                json={"path": alist.root_path, "page": 1, "per_page": 1},
            )
            data = _alist_request_json(response, action="列目录")
        return {
            **base,
            "available": True,
            "write": bool(data.get("write", True)),
            "provider": str(data.get("provider") or ""),
            "upload_api": urljoin(f"{_alist_api_base(cfg)}/", "api/fs/put"),
        }
    except Exception as exc:
        return {**base, "available": False, "error": str(exc)}

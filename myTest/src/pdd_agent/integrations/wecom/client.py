"""企业微信 Webhook 客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.wecom.config import (
    WecomConfig,
    load_wecom_config,
    resolve_alert_webhook_url,
    resolve_daily_report_webhook_url,
    wecom_configured,
)

logger = get_logger(__name__)

WECOM_WEBHOOK_SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


class WecomAPIError(Exception):
    def __init__(self, message: str, *, errcode: int | None = None, payload: dict | None = None) -> None:
        super().__init__(message)
        self.errcode = errcode
        self.payload = payload or {}


def build_text_payload(content: str) -> dict[str, Any]:
    return {
        "msgtype": "text",
        "text": {"content": content},
    }


def build_markdown_payload(content: str, *, version: str = "markdown") -> dict[str, Any]:
    msgtype = "markdown_v2" if version == "markdown_v2" else "markdown"
    return {"msgtype": msgtype, msgtype: {"content": content}}


def send_webhook_payload(
    payload: dict[str, Any],
    *,
    webhook_url: str = "",
    cfg: WecomConfig | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    cfg = cfg or load_wecom_config()
    url = str(webhook_url or resolve_alert_webhook_url(cfg)).strip()
    if not url:
        raise WecomAPIError("未配置 webhook_url")

    try:
        resp = httpx.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise WecomAPIError(f"企业微信网络异常: {exc}") from exc
    except ValueError as exc:
        raise WecomAPIError("企业微信返回非 JSON 响应") from exc

    if not isinstance(data, dict):
        raise WecomAPIError("企业微信返回格式异常")

    errcode = int(data.get("errcode") or 0)
    if errcode != 0:
        raise WecomAPIError(
            str(data.get("errmsg") or "企业微信发送失败"),
            errcode=errcode,
            payload=data,
        )
    return data


def send_markdown(
    content: str,
    *,
    webhook_url: str = "",
    cfg: WecomConfig | None = None,
    version: str = "markdown",
    for_daily_report: bool = False,
) -> dict[str, Any]:
    cfg = cfg or load_wecom_config()
    resolved = str(webhook_url or "").strip()
    if not resolved:
        resolved = (
            resolve_daily_report_webhook_url(cfg)
            if for_daily_report
            else resolve_alert_webhook_url(cfg)
        )
    return send_webhook_payload(
        build_markdown_payload(content, version=version),
        webhook_url=resolved,
        cfg=cfg,
    )


def send_text(
    content: str,
    *,
    webhook_url: str = "",
    cfg: WecomConfig | None = None,
) -> dict[str, Any]:
    return send_webhook_payload(
        build_text_payload(content),
        webhook_url=webhook_url,
        cfg=cfg,
    )


def send_if_enabled(content: str, *, cfg: WecomConfig | None = None) -> dict[str, Any] | None:
    cfg = cfg or load_wecom_config()
    if not wecom_configured(cfg):
        return None
    try:
        return send_text(content, cfg=cfg)
    except WecomAPIError:
        logger.exception("wecom send failed")
        return None

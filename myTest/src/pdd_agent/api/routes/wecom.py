"""企业微信消息推送 API。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.wecom import (
    WecomConfigOut,
    WecomConfigUpdateIn,
    WecomHealthOut,
    WecomTestSendIn,
    WecomTestSendOut,
)
from pdd_agent.integrations.wecom.client import (
    WecomAPIError,
    build_markdown_payload,
    build_text_payload,
    send_webhook_payload,
)
from pdd_agent.integrations.wecom.config import (
    DEFAULT_WECOM_CONFIG_PATH,
    WecomConfig,
    load_wecom_config,
    mask_webhook_url,
    save_wecom_config,
    wecom_configured,
)

router = APIRouter(prefix="/wecom", tags=["wecom"])


def _config_path() -> str:
    return str(Path(os.getenv("WECOM_CONFIG_PATH", DEFAULT_WECOM_CONFIG_PATH)))


def _config_out(cfg: WecomConfig, *, expose_webhook: bool = False) -> WecomConfigOut:
    url = str(cfg.webhook_url or "").strip()
    return WecomConfigOut(
        enabled=bool(cfg.enabled),
        webhook_url=url if expose_webhook else "",
        webhook_url_masked=mask_webhook_url(url) if url else "",
        webhook_configured=bool(url),
        notify_on_listing_failed=bool(cfg.notify_on_listing_failed),
        notify_on_pipeline_failed=bool(cfg.notify_on_pipeline_failed),
        notify_on_commerce_queued=bool(cfg.notify_on_commerce_queued),
        notify_on_commerce_dispatched=bool(cfg.notify_on_commerce_dispatched),
        config_path=_config_path(),
    )


def _merge_webhook_url(incoming: str, existing: str) -> str:
    text = str(incoming or "").strip()
    if text:
        return text
    return str(existing or "").strip()


def _build_test_payload(body: WecomTestSendIn) -> dict:
    if body.msgtype == "raw":
        if not body.raw_payload:
            raise ValueError("raw 模式需提供 raw_payload（完整企业微信消息体）")
        return dict(body.raw_payload)

    content = str(body.content or "").strip()
    if not content:
        raise ValueError("消息内容不能为空")

    if body.msgtype == "text":
        return build_text_payload(content)
    if body.msgtype == "markdown_v2":
        return build_markdown_payload(content, version="markdown_v2")
    return build_markdown_payload(content, version="markdown")


@router.get("/health", response_model=WecomHealthOut)
def wecom_health():
    cfg = load_wecom_config()
    url = str(cfg.webhook_url or "").strip()
    return WecomHealthOut(
        configured=wecom_configured(cfg),
        enabled=bool(cfg.enabled),
        webhook_configured=bool(url),
        config_path=_config_path(),
    )


@router.get("/config", response_model=WecomConfigOut)
def get_wecom_config():
    return _config_out(load_wecom_config())


@router.put("/config", response_model=WecomConfigOut)
def update_wecom_config(body: WecomConfigUpdateIn):
    existing = load_wecom_config()
    webhook_url = _merge_webhook_url(body.webhook_url, existing.webhook_url)
    if body.enabled and not webhook_url:
        raise HTTPException(status_code=400, detail="启用前请填写 Webhook 地址")

    saved = save_wecom_config(
        WecomConfig(
            enabled=bool(body.enabled),
            webhook_url=webhook_url,
            notify_on_listing_failed=bool(body.notify_on_listing_failed),
            notify_on_pipeline_failed=bool(body.notify_on_pipeline_failed),
            notify_on_commerce_queued=bool(body.notify_on_commerce_queued),
            notify_on_commerce_dispatched=bool(body.notify_on_commerce_dispatched),
        )
    )
    return _config_out(saved)


@router.post("/test", response_model=WecomTestSendOut)
def test_wecom_send(body: WecomTestSendIn):
    cfg = load_wecom_config()
    webhook_url = str(body.webhook_url or "").strip()
    if body.use_saved_webhook or not webhook_url:
        webhook_url = str(cfg.webhook_url or "").strip()
    if not webhook_url:
        raise HTTPException(status_code=400, detail="未配置 Webhook 地址")

    try:
        payload = _build_test_payload(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        data = send_webhook_payload(payload, webhook_url=webhook_url, cfg=cfg)
    except WecomAPIError as exc:
        return WecomTestSendOut(
            ok=False,
            errcode=int(exc.errcode or -1),
            errmsg=str(exc),
            payload_sent=payload,
            response=dict(exc.payload or {}),
        )

    return WecomTestSendOut(
        ok=True,
        errcode=0,
        errmsg="ok",
        payload_sent=payload,
        response=data,
    )

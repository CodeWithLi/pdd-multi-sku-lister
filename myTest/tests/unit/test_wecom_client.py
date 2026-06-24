"""企业微信 Webhook 客户端单元测试。"""

from __future__ import annotations

import pytest

from pdd_agent.integrations.wecom.client import (
    WecomAPIError,
    build_markdown_payload,
    build_text_payload,
    send_webhook_payload,
)
from pdd_agent.integrations.wecom.config import WecomConfig, mask_webhook_url


def test_mask_webhook_url():
    url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=1fbf0f3f-aa76-47b2-95d9-4e8e576bbd64"
    masked = mask_webhook_url(url)
    assert "1fbf" in masked
    assert "bbd64" in masked or "bd64" in masked
    assert "1fbf0f3f-aa76-47b2-95d9-4e8e576bbd64" not in masked


def test_build_text_payload():
    payload = build_text_payload("hello")
    assert payload == {"msgtype": "text", "text": {"content": "hello"}}


def test_build_markdown_v2_payload():
    payload = build_markdown_payload("**bold**", version="markdown_v2")
    assert payload["msgtype"] == "markdown_v2"
    assert payload["markdown_v2"]["content"] == "**bold**"


def test_send_webhook_payload_success(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"errcode": 0, "errmsg": "ok"}

    monkeypatch.setattr(
        "pdd_agent.integrations.wecom.client.httpx.post",
        lambda *args, **kwargs: FakeResp(),
    )
    cfg = WecomConfig(webhook_url="https://example.com/webhook?key=abc")
    data = send_webhook_payload(build_text_payload("hi"), cfg=cfg)
    assert data["errcode"] == 0


def test_send_webhook_payload_api_error(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"errcode": 93017, "errmsg": "invalid json"}

    monkeypatch.setattr(
        "pdd_agent.integrations.wecom.client.httpx.post",
        lambda *args, **kwargs: FakeResp(),
    )
    cfg = WecomConfig(webhook_url="https://example.com/webhook?key=abc")
    with pytest.raises(WecomAPIError) as exc:
        send_webhook_payload(build_text_payload("hi"), cfg=cfg)
    assert exc.value.errcode == 93017

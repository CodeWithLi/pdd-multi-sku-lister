"""提交前 AI 改标题：超时、兜底与跳过提交。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from dataclasses import replace

import pytest

from pdd_agent.api.services.submit_ai_title_config_service import SubmitAiTitleConfig
from pdd_agent.skills.listing import listing_submit_ai_title as mod


def _cfg(**overrides) -> SubmitAiTitleConfig:
    base = SubmitAiTitleConfig(
        enabled=True,
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key="primary-key",
        fallback_enabled=True,
        fallback_provider="glm",
        fallback_model="glm-4-flash",
        fallback_base_url="https://open.bigmodel.cn/api/paas/v4",
        fallback_api_key="fallback-key",
        max_image_count=1,
    )
    return replace(base, **overrides)


def test_classify_timeout_exception():
    reason, _ = mod._classify_title_model_exception(TimeoutError("read timeout"))
    assert reason == "model_invoke_timeout"


def test_invoke_title_model_raises_on_thread_timeout(monkeypatch):
    cfg = _cfg()
    image = Path(__file__)

    class _FakeFuture:
        def result(self, timeout=None):
            raise mod.FuturesTimeoutError()

    class _FakePool:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def submit(self, _fn):
            return _FakeFuture()

    monkeypatch.setattr(mod, "ThreadPoolExecutor", lambda **_kwargs: _FakePool())

    with pytest.raises(TimeoutError, match="调用超时"):
        mod._invoke_title_model(
            cfg=cfg,
            prompt="test",
            images=[image],
            account_id="shop",
            label="BD025/第一套图",
            role="主模型",
            request_timeout=0.05,
        )


def test_invoke_title_with_fallback_uses_fallback_after_primary_timeout(monkeypatch):
    cfg = _cfg()
    image = Path(__file__)
    calls: list[str] = []

    def _fake_invoke(**kwargs):
        role = kwargs["role"]
        calls.append(role)
        if role == "主模型":
            raise TimeoutError("primary timeout")
        return "兜底标题"

    monkeypatch.setattr(mod, "_invoke_title_model", _fake_invoke)

    result = mod._invoke_title_with_fallback(
        cfg=cfg,
        prompt="prompt",
        images=[image],
        account_id="shop",
        label="BD025/第一套图",
    )

    assert calls == ["主模型", "兜底模型"]
    assert result["title"] == "兜底标题"
    assert result["fallback_used"] is True
    assert result["primary_reason"] == "model_invoke_timeout"


def test_invoke_title_with_fallback_skips_when_both_fail(monkeypatch):
    cfg = _cfg()
    image = Path(__file__)

    def _fail_invoke(**_kwargs):
        raise TimeoutError("timeout")

    monkeypatch.setattr(mod, "_invoke_title_model", _fail_invoke)

    result = mod._invoke_title_with_fallback(
        cfg=cfg,
        prompt="prompt",
        images=[image],
        account_id="shop",
        label="BD025/第一套图",
    )

    assert result["title"] == ""
    assert result["fallback_used"] is False
    assert result["reason"] == "model_invoke_timeout"


def test_apply_submit_ai_title_before_submit_skips_and_continues(monkeypatch, tmp_path):
    img = tmp_path / "1.jpg"
    img.write_bytes(b"fake")

    monkeypatch.setattr(
        mod,
        "get_submit_ai_title_config",
        lambda: _cfg(),
    )
    monkeypatch.setattr(mod, "_read_title_from_input", lambda _page: "原标题")
    monkeypatch.setattr(
        mod,
        "_invoke_title_with_fallback",
        lambda **_kwargs: {
            "title": "",
            "source": "primary",
            "reason": "model_invoke_timeout",
            "fallback_used": False,
            "primary_reason": "model_invoke_timeout",
            "primary_error": "timeout",
            "fallback_reason": "model_invoke_timeout",
            "fallback_error": "timeout",
        },
    )

    result = mod.apply_submit_ai_title_before_submit(
        MagicMock(),
        account_id="shop",
        label="BD025/第一套图",
        image_paths=[str(img)],
    )

    assert result["ok"] is True
    assert result["applied"] is False
    assert result["reason"] == "model_invoke_timeout"
    assert result["final_title"] == "原标题"

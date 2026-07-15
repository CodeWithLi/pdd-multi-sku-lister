"""失败日志「系统原因」承载 pipeline_id 的封装测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.failure_log_pipeline_system_reason import (
    build_failure_log_system_reason,
    format_pipeline_system_reason,
    parse_pipeline_id_from_system_reason,
    prepare_failure_log_system_reason_kwargs,
    resolve_pipeline_id_for_failure_log,
)


def test_format_pipeline_system_reason():
    assert format_pipeline_system_reason("") == ""
    assert format_pipeline_system_reason("  ") == ""
    assert format_pipeline_system_reason("20260715_130000_ab12cd34") == (
        "[pipeline:20260715_130000_ab12cd34]"
    )


def test_parse_pipeline_id_from_system_reason():
    assert parse_pipeline_id_from_system_reason("") == ""
    assert parse_pipeline_id_from_system_reason("普通诊断文案") == ""
    assert (
        parse_pipeline_id_from_system_reason("[pipeline:20260715_130000_ab12cd34]")
        == "20260715_130000_ab12cd34"
    )
    assert (
        parse_pipeline_id_from_system_reason("前缀[pipeline:pid_x]后缀")
        == "pid_x"
    )


def test_resolve_prefers_explicit_pipeline_id(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.failure_log_pipeline_system_reason.lookup_pipeline_id_for_listing_run",
        lambda run_id="": "from_run",
    )
    assert (
        resolve_pipeline_id_for_failure_log(
            pipeline_id="explicit",
            run_id="run_1",
            system_reason="[pipeline:from_text]",
        )
        == "explicit"
    )


def test_resolve_falls_back_to_system_reason_then_run(monkeypatch):
    calls: list[str] = []

    def fake_lookup(run_id: str = "") -> str:
        calls.append(run_id)
        return "from_run"

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.failure_log_pipeline_system_reason.lookup_pipeline_id_for_listing_run",
        fake_lookup,
    )
    assert (
        resolve_pipeline_id_for_failure_log(
            pipeline_id="",
            run_id="run_1",
            system_reason="[pipeline:from_text]",
        )
        == "from_text"
    )
    assert calls == []
    assert (
        resolve_pipeline_id_for_failure_log(
            pipeline_id="",
            run_id="run_1",
            system_reason="",
        )
        == "from_run"
    )
    assert calls == ["run_1"]


def test_build_failure_log_system_reason_empty_without_pipeline(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.failure_log_pipeline_system_reason.lookup_pipeline_id_for_listing_run",
        lambda run_id="": "",
    )
    assert build_failure_log_system_reason(pipeline_id="", run_id="r1") == ""
    assert build_failure_log_system_reason(pipeline_id="p1") == "[pipeline:p1]"


def test_prepare_failure_log_system_reason_kwargs(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.failure_log_pipeline_system_reason.lookup_pipeline_id_for_listing_run",
        lambda run_id="": "",
    )
    out = prepare_failure_log_system_reason_kwargs(
        {
            "account_id": "store_A",
            "failure_reason": "校验失败",
            "system_reason": "旧诊断文案",
            "pipeline_id": "pipe_9",
            "run_id": "run_9",
        }
    )
    assert out["system_reason"] == "[pipeline:pipe_9]"
    assert out["failure_reason"] == "校验失败"
    assert out["pipeline_id"] == "pipe_9"
    assert out["run_id"] == "run_9"

    out_empty = prepare_failure_log_system_reason_kwargs(
        {
            "system_reason": "旧诊断文案",
            "pipeline_id": "",
            "run_id": "",
        }
    )
    assert out_empty["system_reason"] == ""

"""失败日志挂回原链路 — 解析与精准状态更新单测。"""

from __future__ import annotations

from types import SimpleNamespace

from pdd_agent.api.services.failure_log_attach_retry.bridge import (
    is_attach_source_pipeline_enabled,
    try_process_attach_source_pipeline,
)
from pdd_agent.api.services.failure_log_attach_retry.capture_pipeline_id import (
    evaluate_capture_pipeline_id_gate,
    is_attach_path_fully_enabled,
)
from pdd_agent.api.services.failure_log_attach_retry.resolve import (
    merchant_code_matches_stage_row,
    resolve_attach_targets,
)


def test_merchant_code_matches_stage_row_by_selector_tail():
    assert merchant_code_matches_stage_row(
        "ABC123",
        {"product_selector": "母码/套图/ABC123", "listing_label": "母码/套图/ABC123"},
    )
    assert not merchant_code_matches_stage_row(
        "ABC123",
        {"product_selector": "母码/套图/OTHER", "listing_label": "OTHER"},
    )


def test_resolve_attach_targets_prefers_failed_listing(monkeypatch):
    stages = [
        {
            "batch_index": 0,
            "product_selector": "a/b/CODE1",
            "listing_label": "a/b/CODE1",
            "listing_status": "success",
            "limited_time_status": "success",
            "pdd_product_id": "p1",
        },
        {
            "batch_index": 1,
            "product_selector": "a/b/CODE1",
            "listing_label": "a/b/CODE1",
            "listing_status": "failed",
            "limited_time_status": "pending",
            "pdd_product_id": "",
        },
    ]
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_batch_product_stage_tracker.list_pipeline_batch_product_stages",
        lambda **kwargs: stages,
    )
    result = resolve_attach_targets(pipeline_id="pipe1", merchant_code="CODE1")
    assert result["matched_count"] == 2
    assert result["targets"][0]["batch_index"] == 1
    assert result["targets"][0]["listing_status"] == "failed"


def test_is_attach_source_pipeline_enabled():
    assert is_attach_source_pipeline_enabled(None) is False
    assert is_attach_source_pipeline_enabled(SimpleNamespace(attach_source_pipeline_enabled=True))
    assert not is_attach_source_pipeline_enabled(
        SimpleNamespace(attach_source_pipeline_enabled=False)
    )


def test_attach_path_requires_both_switches():
    assert not is_attach_path_fully_enabled(
        SimpleNamespace(attach_source_pipeline_enabled=True, capture_pipeline_id_enabled=False)
    )
    assert not is_attach_path_fully_enabled(
        SimpleNamespace(attach_source_pipeline_enabled=False, capture_pipeline_id_enabled=True)
    )
    assert is_attach_path_fully_enabled(
        SimpleNamespace(attach_source_pipeline_enabled=True, capture_pipeline_id_enabled=True)
    )


def test_capture_gate_skips_without_pipeline_id(monkeypatch):
    watch = SimpleNamespace(capture_pipeline_id_enabled=True)
    monkeypatch.setattr(
        "pdd_agent.api.services.failure_log_attach_retry.capture_pipeline_id.extract_captured_pipeline_id",
        lambda candidate: "",
    )
    gate = evaluate_capture_pipeline_id_gate({"record_id": "r1"}, watch=watch)
    assert gate["enabled"] is True
    assert gate["skipped"] is True
    assert gate["reason"] == "missing_source_pipeline_id"


def test_capture_gate_ok_with_pipeline_id(monkeypatch):
    watch = SimpleNamespace(capture_pipeline_id_enabled=True)
    monkeypatch.setattr(
        "pdd_agent.api.services.failure_log_attach_retry.capture_pipeline_id.extract_captured_pipeline_id",
        lambda candidate: "pipe_abc",
    )
    gate = evaluate_capture_pipeline_id_gate({"record_id": "r1"}, watch=watch)
    assert gate["ok"] is True
    assert gate["skipped"] is False
    assert gate["pipeline_id"] == "pipe_abc"


def test_try_process_returns_none_when_capture_disabled():
    watch = SimpleNamespace(
        attach_source_pipeline_enabled=True,
        capture_pipeline_id_enabled=False,
    )
    out = try_process_attach_source_pipeline(
        {"record_id": "rec1", "merchant_code": "M1"},
        watch=watch,
    )
    assert out is None


def test_try_process_skips_without_source_pipeline_id(monkeypatch):
    watch = SimpleNamespace(
        attach_source_pipeline_enabled=True,
        capture_pipeline_id_enabled=True,
        pipeline_report_platforms=["拼多多"],
        pipeline_material_source="",
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.config.load_feishu_config",
        lambda: SimpleNamespace(pdd_upload_log=SimpleNamespace(failure_cycle_relist_watch=watch)),
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.failure_log_attach_retry.capture_pipeline_id.extract_captured_pipeline_id",
        lambda candidate: "",
    )
    out = try_process_attach_source_pipeline(
        {
            "record_id": "rec1",
            "merchant_code": "M1",
            "account_name": "店铺A",
            "report_platform": "拼多多",
        },
        watch=watch,
        skip_claim=True,
    )
    assert out is not None
    assert out["ok"] is True
    assert out["skipped"] is True
    assert out["reason"] == "missing_source_pipeline_id"


def test_try_process_returns_none_when_disabled():
    watch = SimpleNamespace(
        attach_source_pipeline_enabled=False,
        capture_pipeline_id_enabled=False,
    )
    out = try_process_attach_source_pipeline(
        {"record_id": "rec1", "merchant_code": "M1"},
        watch=watch,
    )
    assert out is None

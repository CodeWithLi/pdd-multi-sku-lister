"""任务失败/取消时飞书回写兜底测试。"""

from __future__ import annotations

from pdd_agent.api.services.task_runner import (
    _extract_limited_time_price_filter_errors,
    _extract_per_product_activity_errors,
    _normalize_terminal_failure_result,
    _summarize_campaign_message,
    ensure_feishu_logged_for_terminal_run,
)
from pdd_agent.domain.enums import AgentKind, RunStatus


def test_normalize_terminal_failure_result_for_cancel():
    payload = _normalize_terminal_failure_result({}, run_status=RunStatus.CANCELED)
    assert "取消" in payload["error"]


def test_summarize_campaign_message_time_requirement():
    result = {
        "results": [
            {
                "status": "failed",
                "step": "product_time_requirement_not_met",
                "error": "商品需过24h后才可以报活动",
            }
        ]
    }
    msg = _summarize_campaign_message(result)
    assert msg == "商品需过24h后才可以报活动"


def test_extract_per_product_activity_errors_maps_partial_not_eligible():
    result = {
        "results": [
            {
                "status": "failed",
                "step": "product_not_eligible_for_activity",
                "error": "部分商品不可报名活动，已取消操作：968628035598",
                "product_ids": ["968628035598"],
            }
        ]
    }
    errors = _extract_per_product_activity_errors(
        result,
        fallback_error="部分商品不可报名活动，已取消操作：968628035598",
        product_ids=["968628035598"],
    )
    assert errors["968628035598"] == "商品需过24h后才可以报活动"


def test_extract_limited_time_price_filter_errors_on_partial_success():
    result = {
        "results": [
            {
                "status": "success",
                "price_filter": {
                    "status": "success",
                    "kept_product_ids": ["111", "222"],
                    "deleted_product_ids": ["333", "444"],
                    "decisions": [
                        {"product_id": "111", "keep": True},
                        {"product_id": "222", "keep": True},
                        {"product_id": "333", "keep": False, "reason": "price_out_of_range_or_missing_rule"},
                        {"product_id": "444", "keep": False, "reason": "price_out_of_range_or_missing_rule"},
                    ],
                },
            }
        ]
    }
    errors = _extract_limited_time_price_filter_errors(result)
    assert set(errors) == {"333", "444"}
    assert "价格区间" in errors["333"]


def test_extract_per_product_activity_errors_from_eligibility():
    result = {
        "results": [
            {
                "status": "failed",
                "step": "product_time_requirement_not_met",
                "error": "商品需过24h后才可以报活动",
                "eligibility": {
                    "time_blocked": [
                        {"product_id": "968599179476", "reason_text": "需等待1天"},
                    ]
                },
            }
        ]
    }
    errors = _extract_per_product_activity_errors(result, fallback_error="fallback")
    assert errors["968599179476"] == "商品需过24h后才可以报活动"


def test_ensure_feishu_logged_for_terminal_run_limited_time(monkeypatch):
    captured: list[dict] = []

    def fake_schedule(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(
        "pdd_agent.api.services.task_runner._schedule_feishu_limited_time_status",
        fake_schedule,
    )

    ensure_feishu_logged_for_terminal_run(
        run_id="run_lt_1",
        agent=AgentKind.CAMPAIGN.value,
        account_id="store_A",
        payload={
            "campaign_type": "limited_time_setup",
            "pdd_product_ids": ["968599179476"],
        },
        result={"error": "Target page closed"},
        error="Target page closed",
        run_status=RunStatus.FAILED,
    )

    assert captured
    assert captured[0]["result"]["error"] == "Target page closed"
    assert captured[0]["status"] == RunStatus.FAILED


def test_ensure_feishu_logged_for_terminal_run_is_idempotent(monkeypatch):
    from pdd_agent.api.services import task_runner as tr

    tr._feishu_terminal_logged_run_ids.clear()
    calls: list[str] = []

    def fake_schedule(**kwargs):
        calls.append(str(kwargs.get("run_id") or ""))

    monkeypatch.setattr(
        "pdd_agent.api.services.task_runner._schedule_feishu_limited_time_status",
        fake_schedule,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.task_runner.TaskRunStore",
        lambda: type("S", (), {"load": lambda self, _rid: None})(),
    )

    kwargs = {
        "run_id": "run_once_dedupe_test",
        "agent": "campaign",
        "account_id": "store_A",
        "payload": {"campaign_type": "limited_time_setup", "pdd_product_ids": ["1"]},
        "result": {"error": "failed"},
        "error": "failed",
        "run_status": RunStatus.FAILED,
    }
    ensure_feishu_logged_for_terminal_run(**kwargs)
    ensure_feishu_logged_for_terminal_run(**kwargs)
    assert calls == ["run_once_dedupe_test"]


def test_schedule_feishu_limited_time_status_claims_run_id_once(monkeypatch):
    from pdd_agent.api.services import task_runner as tr

    tr._feishu_terminal_logged_run_ids.clear()
    calls = 0

    def fake_upload(**kwargs):
        return None

    def fake_activity(**kwargs):
        nonlocal calls
        calls += 1

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_upload_sync.schedule_pdd_upload_limited_time_status",
        fake_upload,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_activity_log_sync.schedule_pdd_activity_log_limited_time",
        fake_activity,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_activity_log_sync.safe_load_activity_log_product_context",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_upload_sync.extract_product_ids_for_limited_time_status",
        lambda selected, result: list(selected),
    )
    monkeypatch.setattr(tr, "_account_display_name", lambda _aid: "store")

    kwargs = {
        "account_id": "store_A",
        "selected_product_ids": ["968599179476"],
        "result": {"error": "failed"},
        "status": RunStatus.FAILED,
        "run_id": "lt_run_claim_test",
    }
    tr._schedule_feishu_limited_time_status(**kwargs)
    tr._schedule_feishu_limited_time_status(**kwargs)
    assert calls == 1

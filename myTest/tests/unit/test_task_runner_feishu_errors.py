"""任务失败/取消时飞书回写兜底测试。"""

from __future__ import annotations

from pdd_agent.api.services.task_runner import (
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
                "error": "当前商品未满足时间要求，已取消报名：968599179476（需等待1天）",
            }
        ]
    }
    msg = _summarize_campaign_message(result)
    assert "未满足时间要求" in msg


def test_extract_per_product_activity_errors_from_eligibility():
    result = {
        "results": [
            {
                "status": "failed",
                "step": "product_time_requirement_not_met",
                "error": "当前商品未满足时间要求，已取消报名：968599179476（需等待1天）",
                "eligibility": {
                    "time_blocked": [
                        {"product_id": "968599179476", "reason_text": "需等待1天"},
                    ]
                },
            }
        ]
    }
    errors = _extract_per_product_activity_errors(result, fallback_error="fallback")
    assert errors["968599179476"] == "当前商品未满足时间要求：需等待1天"


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

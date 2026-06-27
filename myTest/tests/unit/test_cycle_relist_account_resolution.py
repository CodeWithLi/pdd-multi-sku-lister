"""失败日志循环上架 — 按店铺解析 account_id。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.core.account_display import resolve_cycle_relist_account_id
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger import (
    process_failure_cycle_relist_candidate,
)


def test_resolve_cycle_relist_account_id_by_display_name():
    with patch(
        "pdd_agent.core.account_display.resolve_account_id_by_display_name",
        return_value="store_A",
    ):
        account_id, error = resolve_cycle_relist_account_id(account_name="兔兔潮玩屋")
    assert account_id == "store_A"
    assert error == ""


def test_resolve_cycle_relist_account_id_prefers_explicit_account_id():
    settings = SimpleNamespace(
        accounts=[
            SimpleNamespace(account_id="store_B", enabled=True),
        ]
    )
    with patch("pdd_agent.core.account_display.load_yaml_settings", return_value=settings):
        account_id, error = resolve_cycle_relist_account_id(
            account_name="兔兔潮玩屋",
            account_id="store_B",
        )
    assert account_id == "store_B"
    assert error == ""


def test_resolve_cycle_relist_account_id_returns_error_when_unknown():
    with patch(
        "pdd_agent.core.account_display.resolve_account_id_by_display_name",
        return_value="",
    ):
        account_id, error = resolve_cycle_relist_account_id(account_name="未知店铺")
    assert account_id == ""
    assert "无法识别店铺" in error


def test_process_candidate_uses_resolved_store(monkeypatch):
    from pdd_agent.integrations.feishu.config import PddFailureCycleRelistWatchConfig

    watch = PddFailureCycleRelistWatchConfig(
        trigger_pipeline_on_discover=True,
        pipeline_activity_ids=["20981"],
    )
    cfg = MagicMock()
    cfg.pdd_upload_log.failure_cycle_relist_watch = watch

    claim = MagicMock()
    claim.ok = True
    claim.claimed = True
    claim.to_dict.return_value = {"ok": True, "claimed": True}

    captured: dict = {}

    def _start(**kwargs):
        captured.update(kwargs)
        return {"pipeline_id": "pipe-1", "product_codes": ["BD023B"]}

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.try_claim_cycle_relist",
        lambda *args, **kwargs: claim,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.resolve_cycle_relist_account_id",
        lambda **kwargs: ("store_B", ""),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.start_integrated_pipeline",
        _start,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.update_integrated_pipeline",
        lambda *args, **kwargs: None,
    )

    outcome = process_failure_cycle_relist_candidate(
        {
            "record_id": "rec1",
            "merchant_code": "BD023B",
            "account_name": "其它潮玩屋",
            "account_id": "store_B",
            "report_platform": "拼多多",
        },
        config=cfg,
        watch=watch,
    )

    assert outcome["ok"] is True
    assert outcome["account_id"] == "store_B"
    assert captured["account_id"] == "store_B"

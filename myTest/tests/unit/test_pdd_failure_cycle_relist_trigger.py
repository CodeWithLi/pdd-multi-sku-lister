"""失败日志循环上架触发整合链路测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.integrations.feishu.config import PddFailureCycleRelistWatchConfig
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger import (
    resolve_default_pipeline_activity_ids,
    resolve_listing_selectors_for_merchant_code,
    process_failure_cycle_relist_candidate,
)


def test_resolve_default_pipeline_activity_ids():
    cfg = MagicMock()
    cfg.pdd_activity_log.activity_618_id = "20981"
    cfg.pdd_activity_log.activity_discount_id = "21365"
    assert resolve_default_pipeline_activity_ids(cfg) == ["20981", "21365"]


def test_resolve_listing_selectors_exact_match(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger._catalog_index",
        lambda **kwargs: {"BD023/第一套图": frozenset({"BD023B"})},
    )
    selectors = resolve_listing_selectors_for_merchant_code("BD023B")
    assert selectors == ["BD023/第一套图/BD023B"]


def test_process_candidate_starts_pipeline(monkeypatch):
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

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.try_claim_cycle_relist",
        lambda *args, **kwargs: claim,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.resolve_cycle_relist_account_id",
        lambda **kwargs: ("shop-1", ""),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.start_integrated_pipeline",
        lambda **kwargs: {"pipeline_id": "pipe-1", "product_codes": ["BD023/第一套图/BD023B"]},
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.update_integrated_pipeline",
        lambda *args, **kwargs: None,
    )

    outcome = process_failure_cycle_relist_candidate(
        {
            "record_id": "rec1",
            "merchant_code": "BD023B",
            "account_name": "兔兔潮玩屋",
            "report_platform": "拼多多",
        },
        config=cfg,
        watch=watch,
    )
    assert outcome["ok"] is True
    assert outcome["pipeline_id"] == "pipe-1"
    assert outcome["product_codes"] == ["BD023/第一套图/BD023B"]


def test_process_candidate_uses_cycle_relist_input_mode(monkeypatch):
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
        return {"pipeline_id": "pipe-2", "product_codes": ["BD023/第二套图/BD023B毛绒小猫笔袋"]}

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.try_claim_cycle_relist",
        lambda *args, **kwargs: claim,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger.resolve_cycle_relist_account_id",
        lambda **kwargs: ("shop-1", ""),
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
            "record_id": "rec2",
            "merchant_code": "BD023B毛绒小猫笔袋",
            "account_name": "兔兔潮玩屋",
            "report_platform": "拼多多",
        },
        config=cfg,
        watch=watch,
    )
    assert outcome["ok"] is True
    assert captured["listing_input_mode"] == "cycle_relist"
    assert captured["product_codes"] == ["BD023B毛绒小猫笔袋"]
    assert outcome["product_codes"] == ["BD023/第二套图/BD023B毛绒小猫笔袋"]

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
        "pdd_agent.core.account_display.list_account_ids_by_display_name",
        return_value=["store_A"],
    ), patch(
        "pdd_agent.db.repositories.list_busy_account_ids",
        return_value=set(),
    ):
        account_id, error = resolve_cycle_relist_account_id(account_name="兔兔潮玩屋")
    assert account_id == "store_A"
    assert error == ""


def test_list_account_ids_by_display_name_reads_db_shop_display_name():
    with patch(
        "pdd_agent.core.account_display.list_enabled_account_ids_by_shop_display_name",
        return_value=["store_B", "多多李子2602"],
    ), patch(
        "pdd_agent.core.account_display._account_id_exists",
        side_effect=lambda aid: aid in {"store_B", "多多李子2602"},
    ), patch(
        "pdd_agent.core.account_display.list_account_configs",
        return_value=[],
    ), patch(
        "pdd_agent.db.repositories.list_login_status_rows",
        return_value=[],
    ):
        from pdd_agent.core.account_display import list_account_ids_by_display_name

        ids = list_account_ids_by_display_name("咕噜咕噜时尚店")
    assert ids == ["store_B", "多多李子2602"]


def test_resolve_cycle_relist_account_id_matches_db_shop_name():
    with patch(
        "pdd_agent.core.account_display.list_account_ids_by_display_name",
        return_value=["多多李子2603"],
    ), patch(
        "pdd_agent.db.repositories.list_busy_account_ids",
        return_value=set(),
    ):
        account_id, error = resolve_cycle_relist_account_id(account_name="啦啦啦甜甜圈时尚店")
    assert account_id == "多多李子2603"
    assert error == ""


def test_resolve_cycle_relist_account_id_prefers_explicit_account_id():
    settings = SimpleNamespace(accounts=[])
    with patch("pdd_agent.core.account_display.load_yaml_settings", return_value=settings), patch(
        "pdd_agent.core.account_display.get_account_config",
        return_value=SimpleNamespace(account_id="store_B", enabled=True, username="多多青提2602"),
    ):
        account_id, error = resolve_cycle_relist_account_id(
            account_name="兔兔潮玩屋",
            account_id="store_B",
        )
    assert account_id == "store_B"
    assert error == ""


def test_resolve_cycle_relist_account_id_returns_error_when_unknown():
    with patch(
        "pdd_agent.core.account_display.list_account_ids_by_display_name",
        return_value=[],
    ):
        account_id, error = resolve_cycle_relist_account_id(account_name="未知店铺")
    assert account_id == ""
    assert "无法识别店铺" in error


def test_resolve_cycle_relist_account_id_picks_idle_sibling_account():
    with patch(
        "pdd_agent.core.account_display.list_account_ids_by_display_name",
        return_value=["store_A", "多多李子2601"],
    ), patch(
        "pdd_agent.db.repositories.list_busy_account_ids",
        return_value={"store_A"},
    ):
        account_id, error = resolve_cycle_relist_account_id(account_name="兔兔潮玩屋")
    assert account_id == "多多李子2601"
    assert error == ""


def test_pick_cycle_relist_account_falls_back_when_all_busy():
    from pdd_agent.core.account_display import pick_cycle_relist_account_from_candidates

    with patch(
        "pdd_agent.db.repositories.list_busy_account_ids",
        return_value={"store_A", "多多李子2601"},
    ):
        picked = pick_cycle_relist_account_from_candidates(["store_A", "多多李子2601"])
    assert picked == "store_A"


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

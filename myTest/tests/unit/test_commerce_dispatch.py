"""commerce_dispatch Phase 1 单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from sqlalchemy.sql.dml import Delete

from pdd_agent.api.services import commerce_dispatch as cd
from pdd_agent.db.models import AccountLifecycleORM, CommerceIntentORM, ProductClaimORM


@pytest.fixture
def mock_db(monkeypatch):
    store: dict[str, dict] = {
        "lifecycles": {},
        "intents": {},
        "claims": {},
    }

    def fake_scope():
        class Session:
            _pending_lifecycle_id: str = ""
            _pending_account_id: str = ""

            def get(self, model, key):
                if model is AccountLifecycleORM:
                    row = store["lifecycles"].get(key)
                    if row:
                        Session._pending_lifecycle_id = str(row.get("lifecycle_id") or "")
                        Session._pending_account_id = str(key)
                        return _obj(AccountLifecycleORM, row)
                    return None
                if model is CommerceIntentORM:
                    return _obj(CommerceIntentORM, store["intents"].get(key)) if key in store["intents"] else None
                return None

            def add(self, row):
                if isinstance(row, AccountLifecycleORM):
                    store["lifecycles"][row.account_id] = _dump(row)
                elif isinstance(row, CommerceIntentORM):
                    store["intents"][row.intent_id] = _dump(row)

            def merge(self, row):
                if isinstance(row, ProductClaimORM):
                    store["claims"][row.claim_key] = _dump(row)

            def execute(self, stmt):
                if isinstance(stmt, Delete):
                    table_name = getattr(getattr(stmt, "table", None), "name", "")
                    if table_name == "account_lifecycles":
                        store["lifecycles"].pop(Session._pending_account_id, None)
                    elif table_name == "product_claims" and Session._pending_lifecycle_id:
                        for key, claim in list(store["claims"].items()):
                            if claim.get("lifecycle_id") == Session._pending_lifecycle_id:
                                store["claims"].pop(key, None)
                return MagicMock()

            def flush(self):
                return None

            def expunge(self, row):
                return None

            def scalar(self, stmt):
                for intent in store["intents"].values():
                    if intent.get("status") == "pending" and intent.get("dedupe_key"):
                        return _obj(CommerceIntentORM, intent)
                return None

            def scalars(self, stmt):
                captured = stmt

                class R:
                    def all(inner):
                        if "commerce_intents" in str(captured):
                            rows = [
                                _obj(CommerceIntentORM, v)
                                for v in store["intents"].values()
                                if v.get("status") == "pending"
                            ]
                            if "account_id" in str(captured):
                                for v in store["intents"].values():
                                    pass
                                rows = [
                                    _obj(CommerceIntentORM, v)
                                    for v in store["intents"].values()
                                    if v.get("status") == "pending"
                                ]
                            return rows
                        if "account_lifecycles" in str(captured):
                            return [
                                _obj(AccountLifecycleORM, v)
                                for v in store["lifecycles"].values()
                                if v.get("lifecycle_status") not in cd.LIFECYCLE_TERMINAL
                            ]
                        return [_obj(ProductClaimORM, v) for v in store["claims"].values()]

                return R()

        class CM:
            def __enter__(self):
                return Session()

            def __exit__(self, *args):
                return False

        return CM()

    monkeypatch.setattr(cd, "commerce_enabled", lambda: True)
    monkeypatch.setattr(cd, "session_scope", fake_scope)
    return store


def _dump(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _obj(model, data):
    row = model()
    for k, v in data.items():
        setattr(row, k, v)
    return row


def test_evaluate_gate_allows_idle_account(mock_db):
    gate = cd.evaluate_commerce_gate(
        account_id="store_a",
        product_selectors=["BD014A/第一套图"],
        trigger_source="manual",
    )
    assert gate["allowed"] is True


def test_evaluate_gate_blocks_scheduled_account(mock_db):
    wake = datetime.now() + timedelta(hours=20)
    mock_db["lifecycles"]["store_a"] = {
        "account_id": "store_a",
        "lifecycle_id": "lc1",
        "owner_type": "integrated_pipeline",
        "owner_id": "pipe1",
        "trigger_source": "manual",
        "phase": "scheduled",
        "lifecycle_status": cd.LIFECYCLE_SCHEDULED,
        "wake_at": wake,
        "product_selectors": ["BD014A/第一套图"],
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    gate = cd.evaluate_commerce_gate(
        account_id="store_a",
        product_selectors=["BD999A/第一套图"],
        trigger_source="rabbitmq_auto",
    )
    assert gate["allowed"] is False
    assert gate["block_reason"] == "account_scheduled"


def test_gate_integrated_pipeline_start_queues(mock_db):
    mock_db["lifecycles"]["store_a"] = {
        "account_id": "store_a",
        "lifecycle_id": "lc1",
        "owner_type": "integrated_pipeline",
        "owner_id": "pipe1",
        "trigger_source": "manual",
        "phase": "listing",
        "lifecycle_status": cd.LIFECYCLE_ACTIVE,
        "wake_at": None,
        "product_selectors": ["BD014A/第一套图"],
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    queued = cd.gate_integrated_pipeline_start(
        account_id="store_a",
        product_selectors=["BD999A/第一套图"],
        trigger_source="manual",
        pipeline_payload={"activity_ids": ["20981"]},
    )
    assert queued is not None
    assert queued["commerce_queued"] is True
    assert queued["block_reason"] == "account_active"


def test_build_intent_dedupe_key_stable():
    a = cd.build_intent_dedupe_key("store_a", ["BD014B/第一套图", "BD014A/第一套图"])
    b = cd.build_intent_dedupe_key("store_a", ["BD014A/第一套图", "BD014B/第一套图"])
    assert a == b


def test_get_commerce_overview_empty(mock_db):
    overview = cd.get_commerce_overview()
    assert overview["pending_total"] == 0
    assert overview["lifecycles"] == []
    assert overview["pending_intents"] == []


def test_pipeline_lifecycle_status_scheduled():
    row = MagicMock()
    row.status = "running"
    row.current_step = "waiting_activity"
    row.scheduled_activity_at = datetime(2026, 7, 1, 12, 0, 0)
    status, phase, wake = cd._pipeline_lifecycle_status(row)
    assert status == cd.LIFECYCLE_SCHEDULED
    assert phase == "scheduled"
    assert wake == row.scheduled_activity_at


def test_cancel_commerce_intent_pending(mock_db):
    mock_db["intents"]["intent_1"] = {
        "intent_id": "intent_1",
        "account_id": "store_a",
        "trigger_source": "manual",
        "priority": 5,
        "product_selectors": ["BD014A/第一套图"],
        "status": "pending",
        "block_reason": "account_active",
        "block_detail": "",
        "dedupe_key": "k1",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    outcome = cd.cancel_commerce_intent("intent_1")
    assert outcome["ok"] is True
    assert outcome["intent"]["status"] == "canceled"


def test_cancel_commerce_intent_not_pending(mock_db):
    mock_db["intents"]["intent_2"] = {
        "intent_id": "intent_2",
        "account_id": "store_a",
        "trigger_source": "manual",
        "priority": 5,
        "product_selectors": [],
        "status": "dispatched",
        "block_reason": "account_active",
        "block_detail": "",
        "dedupe_key": "k2",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    outcome = cd.cancel_commerce_intent("intent_2")
    assert outcome["ok"] is False
    assert outcome["error"] == "not_pending"


def test_reconcile_commerce_state_calls_helpers(mock_db, monkeypatch):
    calls = {"dispatch": 0}

    monkeypatch.setattr(cd, "nudge_due_scheduled_pipelines", lambda: 2)
    monkeypatch.setattr(cd, "sync_lifecycle_from_active_pipelines", lambda: 1)
    monkeypatch.setattr(cd, "reconcile_stale_lifecycles", lambda: 0)
    monkeypatch.setattr(
        cd,
        "dispatch_all_pending_intents",
        lambda limit=30: calls.__setitem__("dispatch", limit) or [{"pipeline_id": "p1"}],
    )

    result = cd.reconcile_commerce_state(dispatch_limit=15)
    assert result["nudged"] == 2
    assert result["synced"] == 1
    assert result["dispatched_count"] == 1
    assert calls["dispatch"] == 15


def test_intent_to_dict_merged_flag(mock_db):
    row = _obj(
        CommerceIntentORM,
        {
            "intent_id": "intent_m",
            "account_id": "store_a",
            "trigger_source": "manual",
            "priority": 5,
            "product_selectors": [],
            "status": "pending",
            "block_reason": "duplicate_pending",
            "block_detail": "",
            "dedupe_key": "k",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        },
    )
    data = cd.intent_to_dict(row)
    assert data["is_merged"] is True


def test_force_clear_account_lifecycle(mock_db):
    mock_db["lifecycles"]["store_a"] = {
        "account_id": "store_a",
        "lifecycle_id": "lc1",
        "owner_type": "integrated_pipeline",
        "owner_id": "pipe_old",
        "trigger_source": "manual",
        "phase": "listing",
        "lifecycle_status": cd.LIFECYCLE_ACTIVE,
        "wake_at": None,
        "product_selectors": [],
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    mock_db["claims"]["store_a|BD014A/第一套图"] = {
        "claim_key": "store_a|BD014A/第一套图",
        "account_id": "store_a",
        "lifecycle_id": "lc1",
        "listing_selector": "BD014A/第一套图",
        "claimed_at": datetime.now(),
    }
    assert cd._force_clear_account_lifecycle("store_a", reason="test") is True
    assert "store_a" not in mock_db["lifecycles"]
    assert not any(v.get("lifecycle_id") == "lc1" for v in mock_db["claims"].values())


def test_reset_account_clears_intents_and_lifecycle(mock_db, monkeypatch):
    mock_db["intents"]["intent_1"] = {
        "intent_id": "intent_1",
        "account_id": "store_a",
        "trigger_source": "manual",
        "priority": 5,
        "product_selectors": [],
        "status": "pending",
        "block_reason": "account_active",
        "block_detail": "",
        "dedupe_key": "k1",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    mock_db["lifecycles"]["store_a"] = {
        "account_id": "store_a",
        "lifecycle_id": "lc1",
        "owner_type": "integrated_pipeline",
        "owner_id": "pipe_gone",
        "trigger_source": "manual",
        "phase": "listing",
        "lifecycle_status": cd.LIFECYCLE_ACTIVE,
        "wake_at": None,
        "product_selectors": [],
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    monkeypatch.setattr(cd, "_list_non_terminal_pipeline_ids_for_account", lambda _aid: [])
    monkeypatch.setattr(
        "pdd_agent.db.repositories.get_integrated_pipeline",
        lambda _pid: None,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.commerce_queue_reset.cancel_account_queue_tasks",
        lambda _aid: {"ok": True, "canceled_count": 0, "canceled_run_ids": []},
    )
    result = cd.reset_account_commerce_state("store_a", cancel_pipelines=False)
    assert result["ok"] is True
    assert result["canceled_intents"] == 1
    assert result["lifecycle_cleared"] is True

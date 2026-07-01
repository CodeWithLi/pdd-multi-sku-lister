"""店铺运营重置 — task_queue 同步清理。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.api.services.commerce_queue_reset import (
    cancel_account_queue_tasks,
    list_accounts_with_active_queue_tasks,
)


@patch("pdd_agent.api.services.commerce_queue_reset.is_database_available", return_value=False)
def test_list_accounts_empty_when_db_unavailable(mock_db):
    assert list_accounts_with_active_queue_tasks() == []


@patch("pdd_agent.api.services.commerce_queue_reset.cancel_queued_tasks", return_value=["q1"])
@patch("pdd_agent.db.repositories.cancel_running_tasks", return_value=[{"run_id": "r1", "account_id": "store_a"}])
@patch("pdd_agent.api.services.commerce_queue_reset.TaskRunStore")
def test_cancel_account_queue_tasks_marks_run_records(mock_store_cls, mock_cancel_running, mock_cancel_queued):
    mock_store = mock_store_cls.return_value
    mock_store.load.return_value = MagicMock(status="running")

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pdd_agent.api.app":
            raise ImportError("test skip app worker")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        outcome = cancel_account_queue_tasks("store_a")

    assert outcome["ok"] is True
    assert outcome["canceled_count"] == 2
    assert set(outcome["canceled_run_ids"]) == {"r1", "q1"}
    mock_cancel_running.assert_called_once_with(account_id="store_a")
    mock_cancel_queued.assert_called_once_with(account_id="store_a")

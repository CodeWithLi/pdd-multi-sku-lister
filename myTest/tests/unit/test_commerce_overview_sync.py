"""店铺运营 overview 对账测试。"""

from __future__ import annotations

from unittest.mock import patch

from pdd_agent.api.services.commerce_overview_sync import refresh_commerce_overview_state


@patch("pdd_agent.db.session.is_database_available", return_value=True)
@patch(
    "pdd_agent.api.services.commerce_dispatch.sync_lifecycle_from_active_pipelines",
    return_value=2,
)
@patch(
    "pdd_agent.api.services.commerce_dispatch.reconcile_stale_lifecycles",
    return_value=1,
)
def test_refresh_commerce_overview_state(mock_stale, mock_sync, mock_db):
    outcome = refresh_commerce_overview_state()
    assert outcome["ok"] is True
    assert outcome["stale_cleared"] == 1
    assert outcome["synced"] == 2
    mock_stale.assert_called_once()
    mock_sync.assert_called_once()

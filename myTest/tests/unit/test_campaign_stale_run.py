"""活动/推广任务遗留「进行中」记录清理。"""

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.routes import tasks
from pdd_agent.domain.enums import RunStatus


def test_find_running_campaign_run_clears_stale_record():
    stale = SimpleNamespace(run_id="run_stale", status=RunStatus.RUNNING)
    with patch.object(tasks, "_ACTIVE_CAMPAIGN_RUNS", {}):
        with patch("pdd_agent.api.routes.tasks.TaskRunStore") as store_cls:
            store = store_cls.return_value
            store.search_runs.return_value = ([stale], 1)
            with patch.object(tasks, "_campaign_run_is_live", return_value=False):
                with patch.object(tasks, "_finalize_stale_run") as finalize:
                    found = tasks._find_running_campaign_run("store_A")
    assert found == ""
    finalize.assert_called_once_with("run_stale")


def test_find_running_campaign_run_keeps_live_record():
    with patch.object(tasks, "_ACTIVE_CAMPAIGN_RUNS", {"store_A": "run_live"}):
        with patch.object(tasks, "_campaign_run_is_live", return_value=True):
            found = tasks._find_running_campaign_run("store_A")
    assert found == "run_live"

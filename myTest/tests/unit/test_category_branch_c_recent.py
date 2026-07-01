"""分支 C 最近使用选类 / 严格状态检测。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_recent import (
    branch_c_category_path_ready_strict,
    branch_c_needs_recent_category_pick,
    ensure_branch_c_category_selected,
    read_branch_c_category_selection_state,
    run_branch_c_recent_category_pick,
)


def test_path_ready_when_auto_selected():
    page = MagicMock()
    page.run_js.return_value = {
        "onPage": True,
        "blocking": False,
        "autoSelected": True,
        "explicitSelected": False,
        "pathReady": True,
        "recentPaths": [],
    }
    assert branch_c_category_path_ready_strict(page) is True


def test_not_ready_when_blocking_with_recent_paths():
    page = MagicMock()
    page.run_js.return_value = {
        "onPage": True,
        "blocking": True,
        "autoSelected": False,
        "explicitSelected": False,
        "pathReady": False,
        "recentPaths": ["文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋"],
    }
    assert branch_c_category_path_ready_strict(page) is False
    with patch(
        "pdd_agent.skills.listing.category_branch_c_modal.is_modal_blocking_category_advance",
        return_value=False,
    ):
        assert branch_c_needs_recent_category_pick(page) is True


def test_ensure_skips_when_already_ready():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.log_branch_c_recent_diagnostics",
    ):
        assert ensure_branch_c_category_selected(page, "store", "label", "笔袋") is True


def test_run_recent_pick_clicks_and_waits():
    page = MagicMock()
    page.run_js.return_value = {"ok": True, "text": "A > B > C"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        return_value={"recentPaths": ["A > B > C"]},
    ), patch(
        "pdd_agent.skills.listing.upload._confirm_category_picker_selection",
    ), patch(
        "pdd_agent.skills.listing.upload._dismiss_category_search_overlay",
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.time.sleep",
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        side_effect=[False, True],
    ):
        ok = run_branch_c_recent_category_pick(page, "store", "label", "笔袋", max_wait=2)
    assert ok is True


def test_read_state_returns_dict_on_error():
    page = MagicMock()
    page.run_js.side_effect = RuntimeError("boom")
    assert read_branch_c_category_selection_state(page) == {}

"""分支 A 商品分类页逻辑测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing import category_page_flow
from pdd_agent.skills.listing import upload as listing_upload


def test_read_branch_a_confirm_publish_state_ready(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = {
        "ready": True,
        "visible": True,
        "disabled": False,
        "selectedPathReady": True,
        "forceClick": True,
        "x": 100,
        "y": 200,
    }
    state = listing_upload._read_branch_a_confirm_publish_state(page)
    assert state["ready"] is True
    assert state["x"] == 100


def test_click_branch_a_confirm_publish_uses_mouse(monkeypatch):
    page = MagicMock()
    page.run_js.side_effect = [
        {"visible": True, "x": 120.0, "y": 240.0},
    ]
    monkeypatch.setattr(
        listing_upload,
        "_read_branch_a_confirm_publish_state",
        lambda _page: {"visible": True, "x": 120.0, "y": 240.0},
    )
    monkeypatch.setattr(listing_upload, "_blur_page_focus", lambda *_: None)
    monkeypatch.setattr(listing_upload, "_playwright_mouse_at", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._click_branch_a_confirm_publish(page, "store_A", "BD023A") is True


def test_click_category_branch_a_and_advance_success(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(listing_upload, "_confirm_category_picker_selection", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "_dismiss_category_search_overlay", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "_wait_branch_a_confirm_publish_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "_click_branch_a_confirm_publish", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "_wait_for_branch_a_category_advance", lambda *_a, **_k: True)

    ok, err = listing_upload.click_category_branch_a_and_advance(page, "store_A", "BD023A")
    assert ok is True
    assert err == ""


def test_manual_picker_routes_branch_a_only(monkeypatch):
    page = MagicMock()
    branch_a_called = {"n": 0}
    branch_bc_called = {"n": 0}

    def _branch_a(*_a, **_k):
        branch_a_called["n"] += 1
        return True, ""

    def _wait(*_a, **_k):
        branch_bc_called["n"] += 1
        return True

    monkeypatch.setattr(listing_upload, "click_category_branch_a_and_advance", _branch_a)
    monkeypatch.setattr(listing_upload, "_wait_category_submit_ready", _wait)
    monkeypatch.setattr(listing_upload, "_click_category_next_step_burst", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "_wait_for_category_page_advance", lambda *_a, **_k: True)

    ok, err = category_page_flow.click_category_next_and_advance(
        page, "store_A", "BD023A", ui_type="A", mode="manual_picker"
    )
    assert ok is True
    assert branch_a_called["n"] == 1
    assert branch_bc_called["n"] == 0

    branch_a_called["n"] = 0
    ok, err = category_page_flow.click_category_next_and_advance(
        page, "store_A", "BD023A", ui_type="B", mode="manual_picker"
    )
    assert ok is True
    assert branch_a_called["n"] == 0
    assert branch_bc_called["n"] == 1

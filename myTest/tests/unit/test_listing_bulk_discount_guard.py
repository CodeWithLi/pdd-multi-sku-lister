"""满件折扣 Guard 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing import listing_bulk_discount_guard as guard


def test_parse_visible_bulk_discount():
    assert guard.parse_visible_bulk_discount("满2件 9.5 折") == "9.5"
    assert guard.parse_visible_bulk_discount("满2件9.9折") == "9.9"
    assert guard.parse_visible_bulk_discount("无折扣信息") == ""


def test_is_bulk_discount_verified_requires_both_when_visible_present():
    assert guard.is_bulk_discount_verified(
        {"input_value": "9.9", "visible_value": "9.9"},
        target="9.9",
    )
    assert not guard.is_bulk_discount_verified(
        {"input_value": "9.9", "visible_value": "9.5"},
        target="9.9",
    )
    assert guard.is_bulk_discount_verified(
        {"input_value": "9.9", "visible_value": ""},
        target="9.9",
    )


def test_ensure_bulk_discount_before_submit_skips_when_already_ok(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        guard,
        "read_bulk_discount_state",
        lambda *_: {"input_value": "9.9", "visible_value": "9.9"},
    )
    called = {"fill": False}

    def _fail_fill(*_args, **_kwargs):
        called["fill"] = True
        return {"ok": True}

    monkeypatch.setattr(guard, "_set_bulk_discount", _fail_fill)

    settings = {"ok": True, "bulk_discount": {"ok": True}, "shipping_template": {"ok": True}}
    result = guard.ensure_bulk_discount_before_submit(page, "store_A", "BD032B/第一套图", settings)
    assert result["bulk_discount"]["guard"] == "already_ok"
    assert result["ok"] is True
    assert called["fill"] is False


def test_ensure_bulk_discount_before_submit_fills_when_missing(monkeypatch):
    page = MagicMock()
    states = [
        {"input_value": "9.5", "visible_value": "9.5"},
        {"input_value": "9.5", "visible_value": "9.5"},
        {"input_value": "9.9", "visible_value": "9.9"},
    ]
    monkeypatch.setattr(
        guard,
        "read_bulk_discount_state",
        lambda *_: states.pop(0) if states else {"input_value": "9.9", "visible_value": "9.9"},
    )
    monkeypatch.setattr(guard, "_scroll_bulk_discount_section", lambda *_: None)
    monkeypatch.setattr(guard, "_click_bulk_discount_edit", lambda *_: {"ok": True, "marker": "满2件"})
    monkeypatch.setattr(
        guard,
        "_set_bulk_discount",
        lambda *_a, **_k: {"ok": True, "before": "9.5", "after": "9.9"},
    )
    monkeypatch.setattr(guard, "time", MagicMock(sleep=lambda *_: None))

    settings = {"ok": False, "bulk_discount": {"ok": False}, "shipping_template": {"ok": True}}
    result = guard.ensure_bulk_discount_before_submit(page, "store_A", "BD032B/第一套图", settings)
    assert result["bulk_discount"]["guard"] == "filled_ok"
    assert result["ok"] is True


def test_ensure_bulk_discount_before_submit_fails_after_max_attempts(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        guard,
        "read_bulk_discount_state",
        lambda *_: {"input_value": "9.5", "visible_value": "9.5"},
    )
    monkeypatch.setattr(guard, "_scroll_bulk_discount_section", lambda *_: None)
    monkeypatch.setattr(guard, "_click_bulk_discount_edit", lambda *_: {"ok": False})
    monkeypatch.setattr(
        guard,
        "_set_bulk_discount",
        lambda *_a, **_k: {"ok": False, "before": "9.5", "after": "9.5"},
    )
    monkeypatch.setattr(guard, "time", MagicMock(sleep=lambda *_: None))

    settings = {"ok": False, "bulk_discount": {"ok": False}, "shipping_template": {"ok": True}}
    result = guard.ensure_bulk_discount_before_submit(
        page,
        "store_A",
        "BD032B/第一套图",
        settings,
        max_attempts=2,
    )
    assert result["bulk_discount"]["guard"] == "fill_failed"
    assert result["ok"] is False

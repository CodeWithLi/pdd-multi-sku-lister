"""抓取店铺展示名。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_scrape_shop_display_name_sync_persists_name(monkeypatch):
    from pdd_agent.browser import login_health as mod

    class FakeDp:
        url = "https://mms.pinduoduo.com/home"

    monkeypatch.setattr(
        mod,
        "account_profile_lock",
        lambda *a, **k: _FakeLock(),
    )

    class FakePage:
        def evaluate(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        mod,
        "_launch_persistent",
        lambda *a, **k: (
            SimpleNamespace(stop=lambda: None),
            SimpleNamespace(close=lambda: None),
            FakePage(),
        ),
    )
    monkeypatch.setattr(mod, "ensure_login_sync", lambda account, page: FakeDp())
    monkeypatch.setattr(mod, "is_login_url", lambda url: False)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        "pdd_agent.browser.shop_display_name.refresh_shop_display_name",
        lambda aid, dp, **kw: "兔兔潮流屋",
    )

    account = SimpleNamespace(account_id="store_A", username="多多青提2601")
    result = mod.scrape_shop_display_name_sync(SimpleNamespace(), account)

    assert result.ok is True
    assert result.shop_display_name == "兔兔潮流屋"


def test_scrape_shop_display_name_sync_not_logged_in(monkeypatch):
    from pdd_agent.browser import login_health as mod

    class FakeDp:
        url = "https://mms.pinduoduo.com/login"

    monkeypatch.setattr(mod, "account_profile_lock", lambda *a, **k: _FakeLock())
    monkeypatch.setattr(
        mod,
        "_launch_persistent",
        lambda *a, **k: (
            SimpleNamespace(stop=lambda: None),
            SimpleNamespace(close=lambda: None),
            SimpleNamespace(evaluate=lambda *a, **k: None),
        ),
    )
    monkeypatch.setattr(mod, "ensure_login_sync", lambda account, page: FakeDp())
    monkeypatch.setattr(mod, "is_login_url", lambda url: "login" in str(url).lower())
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    account = SimpleNamespace(account_id="store_A", username="多多青提2601")
    result = mod.scrape_shop_display_name_sync(SimpleNamespace(), account)

    assert result.ok is False
    assert "登录" in result.reason


class _FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

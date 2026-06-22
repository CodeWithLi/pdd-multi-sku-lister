"""店铺展示名解析单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.core.account_display import resolve_account_display_name


def test_resolve_account_display_name_prefers_cached_shop_name(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.core.account_display.get_cached_shop_display_name",
        lambda _aid: "兔兔潮玩屋",
    )

    assert resolve_account_display_name("store_A") == "兔兔潮玩屋"


def test_resolve_account_display_name_falls_back_to_username(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.core.account_display.get_cached_shop_display_name",
        lambda _aid: "",
    )
    monkeypatch.setattr(
        "pdd_agent.core.account_display.load_yaml_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        "pdd_agent.core.account_display.get_account_config",
        lambda _settings, _aid: MagicMock(username="多多青提2601"),
    )

    assert resolve_account_display_name("store_A") == "多多青提2601"


def test_scrape_shop_display_name_uses_page_js():
    from pdd_agent.browser import shop_display_name as mod

    dp = MagicMock()
    dp.url = "https://mms.pinduoduo.com/goods/goods_list"
    dp.run_js.return_value = "兔兔潮玩屋"

    assert mod.scrape_shop_display_name(dp, login_username="多多青提2601") == "兔兔潮玩屋"
    dp.run_js.assert_called_once()


def test_scrape_shop_display_name_skips_login_page():
    from pdd_agent.browser.shop_display_name import scrape_shop_display_name

    dp = MagicMock()
    dp.url = "https://mms.pinduoduo.com/login"

    assert scrape_shop_display_name(dp, login_username="多多青提2601") == ""


def test_maybe_refresh_shop_display_name_persists(monkeypatch):
    from pdd_agent.browser import shop_display_name as mod

    saved: list[tuple[str, str]] = []

    monkeypatch.setattr(mod, "get_cached_shop_display_name", lambda _aid: "")
    monkeypatch.setattr(mod, "scrape_shop_display_name", lambda _dp, **kw: "兔兔潮玩屋")
    monkeypatch.setattr(
        mod,
        "update_shop_display_name",
        lambda aid, name: saved.append((aid, name)),
    )

    dp = MagicMock()
    name = mod.maybe_refresh_shop_display_name("store_A", dp, login_username="多多青提2601")
    assert name == "兔兔潮玩屋"
    assert saved == [("store_A", "兔兔潮玩屋")]

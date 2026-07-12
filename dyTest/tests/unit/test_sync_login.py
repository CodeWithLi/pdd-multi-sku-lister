"""sync_login 单元测试。"""

from dy_agent.browser.sync_login import is_login_url, is_likely_logged_in, resolve_account_phone
from dy_agent.core.config import AccountConfig


def test_is_login_url():
    assert is_login_url("https://fxg.jinritemai.com/login/common")
    assert not is_login_url("https://fxg.jinritemai.com/ffa/mshop/homepage")


def test_is_likely_logged_in():
    assert is_likely_logged_in("https://fxg.jinritemai.com/ffa/mshop/homepage")
    assert not is_likely_logged_in("https://fxg.jinritemai.com/login/common")
    assert not is_likely_logged_in("https://fxg.jinritemai.com/")


def test_resolve_account_phone_prefers_phone_field():
    account = AccountConfig(account_id="store_A", phone="17708216145", username="13800138000")
    assert resolve_account_phone(account) == "17708216145"


def test_resolve_account_phone_fallback_username():
    account = AccountConfig(account_id="store_A", phone="", username="17708216145")
    assert resolve_account_phone(account) == "17708216145"

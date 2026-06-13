"""sync_login 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pdd_agent.browser.sync_login import ensure_session_sync, is_login_url


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://mms.pinduoduo.com/login/?redirectUrl=foo", True),
        ("https://mms.pinduoduo.com/home/", False),
        ("https://mms.pinduoduo.com/marketing/act/detail?id=20981", False),
        ("", False),
    ],
)
def test_is_login_url(url: str, expected: bool) -> None:
    assert is_login_url(url) is expected


def test_ensure_session_sync_already_logged_in() -> None:
    page = MagicMock()
    page.url = "https://mms.pinduoduo.com/marketing/activities"
    result = ensure_session_sync(page, account=None)
    assert result["logged_in"] is True
    assert result["relogin"] is False


def test_ensure_session_sync_login_without_account() -> None:
    page = MagicMock()
    page.url = "https://mms.pinduoduo.com/login/"
    result = ensure_session_sync(page, account=None)
    assert result["logged_in"] is False
    assert result["reason"] == "login_required_no_account"


@patch("pdd_agent.browser.sync_login.ensure_login_if_needed_sync")
def test_ensure_session_sync_relogin_success(mock_login: MagicMock) -> None:
    account = MagicMock(account_id="store_A", username="u", password="p")
    page = MagicMock()
    page.url = "https://mms.pinduoduo.com/login/"
    page._page = MagicMock()

    def _after_login(_account, _raw_page):
        page.url = "https://mms.pinduoduo.com/home/"
        return page

    mock_login.side_effect = _after_login
    result = ensure_session_sync(page, account=account)
    assert result["logged_in"] is True
    assert result["relogin"] is True
    mock_login.assert_called_once()

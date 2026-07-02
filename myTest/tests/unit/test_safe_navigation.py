"""safe_navigation 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from playwright.sync_api import Error as PlaywrightError

from pdd_agent.browser.safe_navigation import (
    HOME_URL,
    is_acceptable_mms_url,
    is_navigation_aborted_error,
    safe_goto,
    safe_goto_home,
)


def test_is_navigation_aborted_error():
    assert is_navigation_aborted_error(PlaywrightError("Page.goto: net::ERR_ABORTED at https://mms.pinduoduo.com/home/"))
    assert not is_navigation_aborted_error(RuntimeError("timeout"))


def test_is_acceptable_mms_url():
    assert is_acceptable_mms_url("https://mms.pinduoduo.com/home/")
    assert is_acceptable_mms_url("https://mms.pinduoduo.com/login/")
    assert not is_acceptable_mms_url("https://example.com/")


def test_safe_goto_treats_aborted_redirect_as_success():
    page = MagicMock()
    page.url = "about:blank"

    def _goto(*_args, **_kwargs):
        page.url = "https://mms.pinduoduo.com/login/"
        raise PlaywrightError("Page.goto: net::ERR_ABORTED at https://mms.pinduoduo.com/home/")

    page.goto.side_effect = _goto

    result = safe_goto(page, HOME_URL, retries=1, retry_pause_sec=0)
    assert result == "https://mms.pinduoduo.com/login/"
    assert page.goto.call_count == 1


def test_safe_goto_retries_then_succeeds():
    page = MagicMock()
    page.url = "about:blank"
    calls = {"n": 0}

    def _goto(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PlaywrightError("Page.goto: net::ERR_ABORTED")
        page.url = "https://mms.pinduoduo.com/home/"

    page.goto.side_effect = _goto
    result = safe_goto(page, HOME_URL, retries=3, retry_pause_sec=0)
    assert result == "https://mms.pinduoduo.com/home/"
    assert calls["n"] == 2


def test_safe_goto_skips_when_already_on_mms():
    page = MagicMock()
    page.url = "https://mms.pinduoduo.com/home/"
    result = safe_goto_home(page)
    assert result.endswith("/home/")
    page.goto.assert_not_called()


def test_safe_goto_reraises_non_aborted_error():
    page = MagicMock()
    page.url = "about:blank"
    page.goto.side_effect = RuntimeError("network down")
    with pytest.raises(RuntimeError, match="network down"):
        safe_goto(page, HOME_URL, retries=1, retry_pause_sec=0)

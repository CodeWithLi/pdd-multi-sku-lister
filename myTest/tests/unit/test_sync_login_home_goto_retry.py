"""sync_login_home_goto_retry — ERR_ABORTED 重试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pdd_agent.browser.sync_login_home_goto_retry import goto_home_with_aborted_retry


def test_succeeds_on_first_goto():
    page = MagicMock()
    page.url = "https://mms.pinduoduo.com/home/"

    result = goto_home_with_aborted_retry(page, "https://mms.pinduoduo.com/home/")

    assert result.endswith("/home/")
    page.goto.assert_not_called()


class _FakePage:
    def __init__(self, url: str = "about:blank"):
        self.url = url
        self.goto_calls = 0

    def goto(self, url, **kwargs):
        self.goto_calls += 1
        if self.goto_calls == 1:
            raise Exception("Page.goto: net::ERR_ABORTED at https://mms.pinduoduo.com/home/")
        self.url = "https://mms.pinduoduo.com/home/"


def test_retries_on_err_aborted_then_succeeds():
    page = _FakePage()

    with patch("pdd_agent.browser.sync_login_home_goto_retry.time.sleep"):
        result = goto_home_with_aborted_retry(
            page,
            "https://mms.pinduoduo.com/home/",
            retries=3,
            retry_pause_sec=0,
        )

    assert page.goto_calls == 2
    assert "mms.pinduoduo.com" in result


def test_aborted_but_already_on_mms_is_success():
    page = MagicMock()
    page.url = "about:blank"

    def _goto(*_args, **_kwargs):
        page.url = "https://mms.pinduoduo.com/goods/goods_list"
        raise Exception("Page.goto: net::ERR_ABORTED")

    page.goto.side_effect = _goto

    with patch("pdd_agent.browser.sync_login_home_goto_retry.time.sleep"):
        result = goto_home_with_aborted_retry(page, "https://mms.pinduoduo.com/home/", retries=1)

    assert "mms.pinduoduo.com" in result


def test_non_aborted_error_is_not_retried():
    page = MagicMock()
    page.url = "about:blank"
    page.goto.side_effect = TimeoutError("timeout")

    with pytest.raises(TimeoutError):
        goto_home_with_aborted_retry(page, "https://mms.pinduoduo.com/home/", retries=3)

    assert page.goto.call_count == 1

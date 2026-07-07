"""商品列表 Tab 导航与提交后核验封装测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pdd_agent.skills.listing import goods_list_publish_verify as publish_verify
from pdd_agent.skills.listing import goods_list_tab_navigation as tab_nav


class _FakeRawPage:
    def __init__(self, url: str = "https://mms.pinduoduo.com/goods/goods_list", *, closed: bool = False):
        self.url = url
        self._closed = closed

    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    def bring_to_front(self) -> None:
        return None


class _FakeContext:
    def __init__(self, pages: list[_FakeRawPage]):
        self.pages = pages


class _FakeDpPage:
    def __init__(self, raw_page: _FakeRawPage, *, tab_element=None, js_result=True):
        self._page = raw_page
        self._tab_element = tab_element
        self._js_result = js_result
        self.url = raw_page.url

    def ele(self, selector: str, timeout: float = 3):
        if selector.startswith("text:") and self._tab_element is not None:
            return self._tab_element
        return None

    def run_js(self, *_args, **_kwargs):
        return self._js_result


class _FakeTab:
    clicked = False

    def click(self) -> None:
        self.clicked = True


def test_switch_to_latest_tab_if_opened_closes_stale_goods_list_tab(monkeypatch):
    old_page = _FakeRawPage()
    new_page = _FakeRawPage()
    dp = _FakeDpPage(old_page)

    monkeypatch.setattr(tab_nav, "_live_context_pages", lambda _page: [old_page, new_page])
    monkeypatch.setattr(tab_nav, "_switch_to_latest_tab", lambda page: setattr(page, "_page", new_page) or True)

    switched = tab_nav.switch_to_latest_tab_if_opened(
        dp,
        tabs_before=1,
        account_id="test-store",
        tab_text="已驳回",
    )

    assert switched is True
    assert dp._page is new_page
    assert old_page.is_closed() is True


def test_click_goods_list_tab_switches_when_new_tab_opened(monkeypatch):
    old_page = _FakeRawPage()
    new_page = _FakeRawPage()
    tab = _FakeTab()
    dp = _FakeDpPage(old_page, tab_element=tab)

    calls: list[int] = []

    def _fake_count(_page):
        calls.append(1)
        return 1 if len(calls) == 1 else 2

    monkeypatch.setattr(tab_nav, "count_context_pages", _fake_count)
    monkeypatch.setattr(
        tab_nav,
        "switch_to_latest_tab_if_opened",
        lambda page, before, **kwargs: setattr(page, "_page", new_page) or True,
    )
    monkeypatch.setattr(tab_nav, "time", SimpleNamespace(sleep=lambda *_: None))

    assert tab_nav.click_goods_list_tab(dp, "已驳回", account_id="test-store") is True
    assert tab.clicked is True
    assert dp._page is new_page


def test_capture_publish_outcome_searches_rejected_after_on_sale_not_found(monkeypatch):
    searched_tabs: list[str] = []

    class _Unit:
        listing_label = "测试单元"

    def _fake_search_goods_tab(_page, account_id, unit, *, tab_text, tab_key, **kwargs):
        searched_tabs.append(tab_text)
        if tab_key == "on_sale":
            return {"status": "not_found", "tab": tab_key}
        if tab_key == "rejected":
            return {
                "status": "captured",
                "tab": tab_key,
                "pdd_product_id": "916918437299",
                "rejection_reason": "分类不匹配",
            }
        return {"status": "not_found", "tab": tab_key}

    monkeypatch.setattr(publish_verify, "_search_goods_tab", _fake_search_goods_tab)

    result = publish_verify.capture_publish_outcome(
        object(),
        "test-store",
        _Unit(),
        "BD102D",
        "测试标题",
    )

    assert searched_tabs == ["在售中", "已驳回"]
    assert result["status"] == "rejected"
    assert result["pdd_product_id"] == "916918437299"


def test_capture_publish_outcome_returns_on_sale_without_checking_rejected(monkeypatch):
    searched_tabs: list[str] = []

    class _Unit:
        listing_label = "测试单元"

    def _fake_search_goods_tab(_page, account_id, unit, *, tab_text, tab_key, **kwargs):
        searched_tabs.append(tab_text)
        return {
            "status": "captured",
            "tab": tab_key,
            "pdd_product_id": "123456789",
        }

    monkeypatch.setattr(publish_verify, "_search_goods_tab", _fake_search_goods_tab)

    result = publish_verify.capture_publish_outcome(
        object(),
        "test-store",
        _Unit(),
        "BD102D",
        "测试标题",
    )

    assert searched_tabs == ["在售中"]
    assert result["status"] == "captured"
    assert result["pdd_product_id"] == "123456789"

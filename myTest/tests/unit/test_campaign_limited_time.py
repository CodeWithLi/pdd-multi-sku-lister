from types import SimpleNamespace

from pdd_agent.skills.campaign.limited_time import ACTIVITY_CREATE_URL_PARTS, _ensure_page_binding


class FakeContext:
    def __init__(self, pages):
        self.pages = pages


class FakePageHandle:
    def __init__(self, url: str, *, closed: bool = False):
        self.url = url
        self._closed = closed
        self.context = None
        self.brought_to_front = False
        self.waited = False

    def is_closed(self) -> bool:
        return self._closed

    def bring_to_front(self) -> None:
        self.brought_to_front = True

    def wait_for_load_state(self, *_args, **_kwargs) -> None:
        self.waited = True


class FakeDpPage:
    def __init__(self, raw_page):
        self._page = raw_page
        self.wait = SimpleNamespace(_page=raw_page)


def test_ensure_page_binding_switches_to_live_activity_page():
    closed_page = FakePageHandle("https://mms.pinduoduo.com/tool/promotion/create?tool_full_channel=10921_77271", closed=True)
    live_page = FakePageHandle("https://mms.pinduoduo.com/tool/promotion/create?tool_full_channel=10921_77271")
    context = FakeContext([closed_page, live_page])
    closed_page.context = context
    live_page.context = context
    page = FakeDpPage(closed_page)

    assert _ensure_page_binding(page, preferred_url_parts=ACTIVITY_CREATE_URL_PARTS, timeout=0) is True
    assert page._page is live_page
    assert page.wait._page is live_page
    assert live_page.brought_to_front is True


def test_ensure_page_binding_returns_false_when_no_live_page():
    closed_page = FakePageHandle("https://mms.pinduoduo.com/tool/promotion/create?tool_full_channel=10921_77271", closed=True)
    context = FakeContext([])
    closed_page.context = context
    page = FakeDpPage(closed_page)

    assert _ensure_page_binding(page, preferred_url_parts=ACTIVITY_CREATE_URL_PARTS, timeout=0) is False

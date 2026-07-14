"""publish_price_stock 单元测试。"""

from dy_agent.skills.listing.publish_page_flow import detect_publish_page_step3
from dy_agent.skills.listing.publish_price_stock import is_ai_assistant_spec_page, is_manual_spec_page


class _FakeLocator:
    def __init__(self, text: str):
        self._text = text

    def inner_text(self, timeout=0):
        return self._text


class _FakePage:
    def __init__(self, text: str):
        self._text = text

    def locator(self, selector: str):
        return _FakeLocator(self._text)


def test_is_manual_spec_page():
    page = _FakePage("价格库存 规格设置 颜色分类 尺寸大小 价格与库存 价格 现货库存")
    assert is_manual_spec_page(page) is True


def test_is_ai_assistant_spec_page():
    page = _FakePage("规格设置 AI 智能填写助手 切换手动填写")
    assert is_ai_assistant_spec_page(page) is True


def test_detect_publish_page_step3():
    page = _FakePage("颜色分类 尺寸大小 价格与库存")
    assert detect_publish_page_step3(page) is True

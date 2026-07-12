"""listing_options / publish_page_flow 单元测试。"""

from dy_agent.core.config import ListingConfig, YamlSettings
from dy_agent.skills.listing.listing_options import listing_options_from_settings
from dy_agent.skills.listing.publish_page_flow import detect_publish_page_variant


class _FakeBody:
    inner_text = "商品发布 主图上传 商品标题 商品类目"


class _FakeLocator:
    def __init__(self, text: str):
        self._text = text

    def inner_text(self, timeout=0):
        return self._text


class _FakePage:
    url = "https://fxg.jinritemai.com/ffa/mcreate/index"

    def locator(self, selector: str):
        return _FakeLocator(_FakeBody.inner_text)


def test_listing_options_from_settings():
    settings = YamlSettings(
        listing=ListingConfig(
            category_next_burst_demo=False,
            accessory_cost_pricing=True,
        )
    )
    opts = listing_options_from_settings(settings)
    assert opts.category_next_burst_demo is False
    assert opts.accessory_cost_pricing is True
    assert opts.title_mode == "page_ai"


def test_detect_publish_page_variant_standard_v1():
    assert detect_publish_page_variant(_FakePage()) == "standard_v1"


def test_detect_publish_page_variant_unknown():
    class UnknownPage:
        url = "https://example.com"

        def locator(self, selector: str):
            return _FakeLocator("hello")

    assert detect_publish_page_variant(UnknownPage()) == "unknown"

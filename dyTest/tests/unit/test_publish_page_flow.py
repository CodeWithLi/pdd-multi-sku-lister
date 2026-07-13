"""listing_options / publish_page_flow 单元测试。"""

from dy_agent.core.config import ListingConfig, YamlSettings
from dy_agent.skills.listing.listing_options import listing_options_from_settings
from dy_agent.skills.listing.publish_page_flow import (
    detect_publish_page_step2,
    detect_publish_page_variant,
    wait_for_publish_page_ready,
)


class _FakeBody:
    inner_text = "商品发布 主图上传 商品标题 商品类目"


class _FakeLocator:
    def __init__(self, text: str = "", *, count: int = 0):
        self._text = text
        self._count = count

    def inner_text(self, timeout=0):
        return self._text

    def count(self):
        return self._count


class _FakePage:
    url = "https://fxg.jinritemai.com/ffa/mcreate/index"

    def locator(self, selector: str):
        if selector == "body":
            return _FakeLocator(_FakeBody.inner_text)
        return _FakeLocator(count=0)


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


def test_detect_publish_page_variant_relaxed_text():
    class RelaxedPage:
        url = "https://fxg.jinritemai.com/ffa/g/create"

        def locator(self, selector: str):
            return _FakeLocator("发布商品 上传主图 商品标题 下一步")

    assert detect_publish_page_variant(RelaxedPage()) == "standard_v1"


def test_detect_publish_page_variant_g_create_dom_fallback():
    class GCreatePage:
        url = "https://fxg.jinritemai.com/ffa/g/create?btm_show_id=abc"

        def locator(self, selector: str):
            if selector == "body":
                return _FakeLocator("上传主图 填写标题")
            if 'input[type="file"]' in selector:
                return _FakeLocator(count=2)
            if "placeholder" in selector:
                return _FakeLocator(count=1)
            return _FakeLocator()

    assert detect_publish_page_variant(GCreatePage()) == "standard_v1"


def test_detect_publish_page_variant_unknown():
    class UnknownPage:
        url = "https://example.com"

        def locator(self, selector: str):
            return _FakeLocator("hello")

    assert detect_publish_page_variant(UnknownPage()) == "unknown"


def test_wait_for_publish_page_ready_immediate():
    assert wait_for_publish_page_ready(_FakePage(), timeout=0.1) == "standard_v1"


def test_detect_publish_page_step2():
    class Step2Page:
        url = "https://fxg.jinritemai.com/ffa/mcreate/index"

        def locator(self, selector: str):
            return _FakeLocator("商品发布 白底图 上传白底图 商品详情 上传图片")

    assert detect_publish_page_step2(Step2Page()) is True

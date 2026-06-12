from types import SimpleNamespace

from pdd_agent.skills.campaign.limited_time import ACTIVITY_CREATE_URL_PARTS, _ensure_page_binding
from pdd_agent.skills.campaign.limited_time import _campaign_price_candidates
from pdd_agent.skills.campaign.price_rules import price_rule_candidates, normalize_price_code


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


def test_price_rule_candidates_support_combo_and_label_suffix():
    assert normalize_price_code("BD004A帆布KT猫笔袋") == "BD004A"
    assert price_rule_candidates("BD046A+AXBD001A") == [
        "BD046A+AXBD001A",
        "BD046A",
        "AXBD001A",
    ]


def test_campaign_price_candidates_use_first_sku_snapshot():
    row = SimpleNamespace(
        mapping_id="m1",
        pdd_product_id="965068015115",
        product_code="BD046A",
        family_code="BD046",
        image_set="第一套",
        spec_metadata={
            "skus": [
                {
                    "combo_folder": "BD046A",
                    "style_code": "BD046A",
                    "model_code": "BD046A",
                },
                {
                    "combo_folder": "BD046A+AXBD001A",
                    "style_code": "BD046A",
                    "model_code": "AXBD001A",
                }
            ]
        },
    )

    result = _campaign_price_candidates(row)

    assert result["pdd_product_id"] == "965068015115"
    assert "AXBD001A" in result["price_rule_candidates"]
    assert result["first_sku"]["combo_folder"] == "BD046A"

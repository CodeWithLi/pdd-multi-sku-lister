from types import SimpleNamespace

from pdd_agent.skills.campaign.limited_time import (
    ACTIVITY_CREATE_URL_PARTS,
    _campaign_price_candidates,
    _ensure_page_binding,
    _is_sync_marketing_checkbox_label,
    _price_filter_failure_message,
)
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


def test_is_sync_marketing_checkbox_label_supports_new_and_old_text():
    assert _is_sync_marketing_checkbox_label("同步设置惊喜优惠")
    assert _is_sync_marketing_checkbox_label("不改变到手价，创建并更新「全站营销」总优惠金额享更多权益")
    assert not _is_sync_marketing_checkbox_label("我已阅读并同意《外场活动说明》")


def test_price_filter_failure_message_includes_price_detail():
    message = _price_filter_failure_message(
        {
            "status": "no_eligible_products",
            "decisions": [
                {
                    "product_id": "967318341181",
                    "keep": False,
                    "check_price": 25.0,
                    "price_rule": {"code": "BD735A", "min_price": 28.0, "max_price": 35.0},
                }
            ],
        }
    )
    assert "967318341181" in message
    assert "pdd.xls" in message
    assert "BD735A" in message


def test_price_filter_failure_message_when_mapping_missing():
    message = _price_filter_failure_message({"status": "skipped", "reason": "no_published_mapping_ids"})
    assert "pdd.xls" in message
    assert "映射" in message

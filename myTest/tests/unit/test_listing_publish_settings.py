"""listing_publish_settings 单元测试。"""

from pdd_agent.skills.listing import listing_publish_settings as lps


class _FakePage:
    def __init__(self, *, html: str = "", js_results: list | None = None):
        self.html = html
        self._js_results = list(js_results or [])
        self._js_index = 0
        self._eles: dict[str, object] = {}

    def run_js(self, _script: str, *args):
        if self._js_index < len(self._js_results):
            item = self._js_results[self._js_index]
            self._js_index += 1
            return item
        return {"ok": False}

    def ele(self, selector: str, timeout: float = 0):
        return self._eles.get(selector)


def test_js_blocks_contain_key_markers():
    assert "满件折扣" in lps._SET_BULK_DISCOUNT_JS
    assert "满2件折扣" in lps._FIND_DISCOUNT_INPUT_JS
    assert "展开修改" in lps._CLICK_EXPAND_SERVICE_EDIT_JS
    assert "sl_expand_all_button" in lps._CLICK_EXPAND_SERVICE_EDIT_JS
    assert "服务与承诺" in lps._CLICK_SERVICE_TAB_JS
    assert "运费模板" in lps._FIND_SHIPPING_BLOCK_JS
    assert "其他模板" in lps._SELECT_SHIPPING_TEMPLATE_JS
    assert "goods-service" in lps._SHIPPING_COMMON_JS
    assert "isShippingTemplateHeader" in lps._SHIPPING_COMMON_JS
    assert "最新全国" not in lps._SELECT_SHIPPING_TEMPLATE_JS  # passed as arg


def test_is_invalid_shipping_header():
    assert lps._is_invalid_shipping_header("请输入品牌名称搜索") is True
    assert lps._is_invalid_shipping_header("最新全国") is False
    assert lps._is_invalid_shipping_header("最新全网") is False


def test_apply_listing_publish_settings_all_ok():
    page = _FakePage(
        js_results=[
            {"ok": True, "marker": "满2件折扣"},
            {"ok": True, "before": "9.5", "after": "9.9", "verified": True},
            "9.9",
            {"ok": True, "method": "section_heading"},
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
            {"ok": True, "method": "section_heading"},
            {
                "ok": True,
                "method": "tracking_sl_expand_all_button",
                "formReady": True,
                "expandStillVisible": False,
            },
            {
                "formReady": True,
                "expandButtonVisible": False,
                "collapsedSummaryVisible": False,
            },
            {"ok": True, "method": "section_heading"},
            {
                "formReady": True,
                "expandButtonVisible": False,
                "collapsedSummaryVisible": False,
            },
            {
                "formReady": True,
                "expandButtonVisible": False,
                "collapsedSummaryVisible": False,
            },
            {
                "formReady": True,
                "expandButtonVisible": False,
                "collapsedSummaryVisible": False,
                "headerText": "最新全国",
            },
            {
                "found": True,
                "current": "",
                "otherChecked": False,
                "expandButtonVisible": False,
            },
            {"ok": True, "template": "最新全国"},
            {"found": True, "current": "最新全国", "otherChecked": True, "expandButtonVisible": False},
        ]
    )
    result = lps.apply_listing_publish_settings(page, "store_A", "BD001/第一套图")
    assert result["ok"] is True
    assert result["bulk_discount"]["after"] == "9.9"
    assert result["shipping_template"]["template"] == "最新全国"


def test_apply_listing_publish_settings_fails_when_expand_not_working():
    page = _FakePage(
        js_results=[
            {"ok": True, "marker": "满2件折扣"},
            {"ok": True, "before": "9.5", "after": "9.9", "verified": True},
            "9.9",
            {"ok": True, "method": "section_heading"},
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
            {"ok": False, "reason": "expand_button_not_found", "formReady": False},
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
            {"ok": True, "method": "section_heading"},
            {"ok": False, "reason": "expand_button_not_found", "formReady": False},
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
            {"ok": True, "method": "section_heading"},
            {"ok": False, "reason": "expand_button_not_found", "formReady": False},
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
            {"ok": False, "reason": "service_tab_not_found"},
            {"ok": False, "reason": "expand_button_not_found", "formReady": False},
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
            {"ok": False, "reason": "expand_button_not_found", "formReady": False},
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
            {
                "formReady": False,
                "expandButtonVisible": True,
                "collapsedSummaryVisible": True,
            },
        ]
    )
    result = lps.apply_listing_publish_settings(page, "store_A", "BD001/第一套图")
    assert result["ok"] is False
    assert result["shipping_template"]["reason"] == "shipping_section_not_ready"

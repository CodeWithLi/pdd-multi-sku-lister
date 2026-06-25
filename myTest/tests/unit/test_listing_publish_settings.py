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
    assert "展开修改" in lps._CLICK_EXPAND_SERVICE_EDIT_JS
    assert "其他模板" in lps._SELECT_SHIPPING_TEMPLATE_JS
    assert "最新全国" not in lps._SELECT_SHIPPING_TEMPLATE_JS  # passed as arg


def test_apply_listing_publish_settings_all_ok():
    page = _FakePage(
        js_results=[
            {"ok": True, "before": "9.5", "after": "9.9"},
            {"ok": True, "selector": "#tm-plate"},
            {"ok": True, "method": "tracking"},
            {"ok": True, "template": "最新全国"},
        ]
    )
    result = lps.apply_listing_publish_settings(page, "store_A", "BD001/第一套图")
    assert result["ok"] is True
    assert result["bulk_discount"]["after"] == "9.9"
    assert result["shipping_template"]["template"] == "最新全国"


def test_apply_listing_publish_settings_skips_shipping_when_not_expanded():
    page = _FakePage(
        js_results=[
            {"ok": True, "before": "9.5", "after": "9.9"},
            {"ok": True, "selector": "#tm-plate"},
            {"ok": False, "reason": "expand_button_not_found"},
        ]
    )
    result = lps.apply_listing_publish_settings(page, "store_A", "BD001/第一套图")
    assert result["ok"] is False
    assert result["shipping_template"]["reason"] == "service_section_not_expanded"

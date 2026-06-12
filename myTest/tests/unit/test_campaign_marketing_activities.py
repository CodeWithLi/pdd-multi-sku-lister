from types import SimpleNamespace

from pdd_agent.skills.campaign.marketing_activities import (
    KNOWN_MARKETING_ACTIVITIES,
    _collect_blank_click_points,
    _dismiss_marketing_phone_popup,
    _read_marketing_phone_popup,
    _reject_multi_quick_channel,
    _is_activity_detail_ready,
    register_marketing_activity,
    search_marketing_activity,
)


class FakeMouse:
    def __init__(self, page: "FakeDpPage"):
        self._page = page
        self.clicks: list[tuple[float, float]] = []

    def click(self, x, y):
        self.clicks.append((x, y))
        self._page.popup_visible = False


class FakeKeyboard:
    def __init__(self, page: "FakeDpPage"):
        self._page = page
        self.keys: list[str] = []

    def press(self, key: str):
        self.keys.append(key)
        if key == "Escape":
            self._page.popup_visible = False


class FakeDpPage:
    def __init__(
        self,
        *,
        url: str = "https://mms.pinduoduo.com/act/index",
        body_text: str = "",
        popup_visible: bool = False,
    ):
        self.url = url
        self._body_text = body_text
        self.popup_visible = popup_visible
        self.calls: list[tuple[str, object]] = []
        self.mouse = FakeMouse(self)
        self.keyboard = FakeKeyboard(self)
        self._page = SimpleNamespace(
            mouse=self.mouse,
            keyboard=self.keyboard,
            go_back=lambda **kwargs: None,
            is_closed=lambda: False,
            context=SimpleNamespace(on=lambda *args, **kwargs: None),
        )

    def get(self, url: str) -> None:
        self.calls.append(("get", url))
        self.url = url

    def run_js(self, script: str):
        self.calls.append(("run_js", script))
        if "document.body" in script and "innerText" in script:
            return self._body_text
        if "潜力商品报名" in self._body_text and "findExactText('营销活动报名')" not in script:
            if "findPopoverFromButton" in script or "popover_not_open" in script:
                return {"visible": False, "reason": "popover_not_open"}
        if "findExactText('营销活动报名')" in script:
            return {
                "found": True,
                "x": 520,
                "y": 198,
                "method": "header_blank_between_title_and_links",
            }
        if "findPopoverFromButton" in script or "popover_not_open" in script:
            if self.popup_visible:
                return {
                    "visible": True,
                    "kind": "phone_popover",
                    "source": "from_button",
                    "text": "设置营销联系电话并开启改价电话提醒 立即设置",
                    "rect": {
                        "top": 210,
                        "left": 720,
                        "right": 980,
                        "bottom": 360,
                        "width": 260,
                        "height": 150,
                    },
                }
            return {"visible": False, "reason": "popover_not_open"}
        if "filter_tab_not_found" in script or "全部活动" in script:
            return {"clicked": True, "method": "click_filter_tab", "text": "全部活动"}
        if "item.text === '查询'" in script or "item.text === '搜索'" in script:
            return {"clicked": True, "text": "查询"}
        if "setInputValue(input, activityId)" in script:
            return {
                "filled": True,
                "value": "20981",
                "placeholder": "输入活动名称或ID搜索，多个ID以逗号隔开",
                "method": "react_input_setter",
            }
        if "card_count" in script:
            return {
                "matched": True,
                "activity_id": "20981",
                "card_count": 1,
                "title": "【618大促】20981长期报名入口",
                "sample_text": "【618大促】20981长期报名入口 ID: 20981 去报名",
            }
        if "search_input_not_found" in script:
            return {
                "found": True,
                "placeholder": "输入活动名称或ID搜索，多个ID以逗号隔开",
                "value": "",
            }
        return None

    def ele(self, selector: str, timeout: float = 3):
        self.calls.append(("ele", selector))
        return None


def test_collect_blank_click_points_prefers_area_below_small_trigger():
    points = _collect_blank_click_points(
        {"top": 181, "left": 799, "right": 918, "bottom": 195, "width": 119, "height": 14}
    )
    names = [item["name"] for item in points]
    assert "near_trigger" in names
    assert "activity_list" in names


def test_dismiss_marketing_phone_popup_clicks_header_blank():
    page = FakeDpPage(popup_visible=True)
    result = _dismiss_marketing_phone_popup(page, "store_A")
    assert result["dismissed"] is True
    assert page.mouse.clicks
    assert page.mouse.clicks[0] == (520.0, 198.0)
    assert page.popup_visible is False


def test_read_marketing_phone_popup_not_visible():
    page = FakeDpPage(popup_visible=False)
    state = _read_marketing_phone_popup(page)
    assert state["visible"] is False


def test_known_marketing_activities_contains_20981():
    ids = {item["activity_id"] for item in KNOWN_MARKETING_ACTIVITIES}
    assert "20981" in ids


def test_search_marketing_activity_requires_activity_id():
    page = FakeDpPage(
        body_text="营销活动 活动大厅 我能参加的活动 全部活动",
    )
    result = search_marketing_activity(page, "store_A", "")
    assert result["status"] == "failed"
    assert result["step"] == "validate_activity_id"


def test_reject_multi_quick_channel(page=None):
    page = FakeDpPage()
    page.url = "https://mms.pinduoduo.com/act/multi-quick-channel?SceneType=ActivityCard"
    page._body_text = "潜力商品报名 输入商品ID搜索商品"
    result = _reject_multi_quick_channel(page, "store_A", "after_register_now", activity_id="20981")
    assert result is not None
    assert result["status"] == "failed"
    assert result["page_kind"] == "multi_quick_channel"


def test_multi_quick_channel_not_detected_on_index_body_text():
    from pdd_agent.skills.campaign.marketing_activities import _is_multi_quick_channel_page

    page = FakeDpPage(
        url="https://mms.pinduoduo.com/act/index?actHomeActivityType=canEnroll",
        body_text="潜力商品报名 去报名 20981",
    )
    assert _is_multi_quick_channel_page(page) is False


def test_activity_detail_url():
    from pdd_agent.skills.campaign.marketing_activities import _activity_detail_url

    assert _activity_detail_url("20981") == "https://mms.pinduoduo.com/act/detail?id=20981"


def test_activity_detail_not_ready_on_index_with_search_results():
    page = FakeDpPage(
        url="https://mms.pinduoduo.com/act/index?actHomeActivityType=canEnroll",
        body_text="【618大促】20981长期报名入口 去报名 20981",
    )
    assert _is_activity_detail_ready(page, "20981") is False


def test_activity_detail_ready_on_detail_url():
    page = FakeDpPage(
        url="https://mms.pinduoduo.com/act/detail?id=20981",
        body_text="活动详情 20981 立即报名 活动时间",
    )
    assert _is_activity_detail_ready(page, "20981") is True


def test_register_marketing_activity_requires_product_ids(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activities.search_marketing_activity",
        lambda page, account_id, activity_id: {"status": "success", "step": "search_completed"},
    )
    page = FakeDpPage()
    result = register_marketing_activity(page, "store_A", "20981", pdd_product_ids=[])
    assert result["status"] == "failed"
    assert result["step"] == "validate_product_ids"


def test_search_marketing_activity_success_flow(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activities._open_marketing_activities_page",
        lambda page, account_id: True,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activities._activity_search_input_locator",
        lambda page: None,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activities._read_activity_search_input_value",
        lambda page: "20981",
    )
    page = FakeDpPage(
        body_text="营销活动 活动大厅 我能参加的活动 全部活动",
    )
    result = search_marketing_activity(page, "store_A", "20981")
    assert result["status"] == "success"
    assert result["activity_id"] == "20981"
    assert result["results"]["matched"] is True
    assert any(call[0] == "run_js" for call in page.calls)

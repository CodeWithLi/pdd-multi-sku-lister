"""营销活动搜索守卫单元测试。"""

from types import SimpleNamespace

from pdd_agent.skills.campaign.marketing_activity_page_guard import (
    is_marketing_activities_url,
    is_wrong_focus_url,
)
from pdd_agent.skills.campaign.marketing_activity_phone_popup_safe import (
    UNSAFE_BLANK_POINT_NAMES,
    collect_safe_blank_click_points,
)
from pdd_agent.skills.campaign.marketing_activity_register_bridge import (
    register_marketing_activity_guarded,
)
from pdd_agent.skills.campaign.marketing_activity_search_guard import (
    search_marketing_activity_guarded,
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
        search_found: bool = True,
    ):
        self.url = url
        self._body_text = body_text
        self.popup_visible = popup_visible
        self.search_found = search_found
        self.calls: list[tuple[str, object]] = []
        self.mouse = FakeMouse(self)
        self.keyboard = FakeKeyboard(self)
        self._page = SimpleNamespace(
            mouse=self.mouse,
            keyboard=self.keyboard,
            url=url,
            go_back=lambda **kwargs: None,
            is_closed=lambda: False,
            bring_to_front=lambda: None,
            close=lambda: None,
            context=SimpleNamespace(
                on=lambda *args, **kwargs: None,
                pages=[SimpleNamespace(url=url, is_closed=lambda: False, bring_to_front=lambda: None)],
            ),
        )

    def get(self, url: str) -> None:
        self.calls.append(("get", url))
        self.url = url
        self._page.url = url

    def run_js(self, script: str):
        self.calls.append(("run_js", script))
        if "document.body" in script and "innerText" in script and "findExactText" not in script:
            return self._body_text
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
            if self.search_found:
                return {
                    "found": True,
                    "placeholder": "输入活动名称或ID搜索，多个ID以逗号隔开",
                    "value": "",
                }
            return {"found": False, "reason": "search_input_not_found"}
        return None

    def ele(self, selector: str, timeout: float = 3):
        self.calls.append(("ele", selector))
        return None


def test_url_helpers():
    assert is_marketing_activities_url("https://mms.pinduoduo.com/act/index")
    assert not is_marketing_activities_url("about:blank")
    assert is_wrong_focus_url("about:blank")
    assert is_wrong_focus_url("https://mms.pinduoduo.com/pg/feedback?msfrom=mms_sidenav")


def test_collect_safe_blank_click_points_excludes_sidebar(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activities._collect_blank_click_points",
        lambda popup_rect: [
            {"name": "left_sidebar", "x": 110, "y": 320},
            {"name": "activity_list", "x": 360, "y": 420},
        ],
    )
    points = collect_safe_blank_click_points({})
    names = {item["name"] for item in points}
    assert "left_sidebar" not in names
    assert "activity_list" in names
    assert "left_sidebar" in UNSAFE_BLANK_POINT_NAMES


def test_search_marketing_activity_guarded_success(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activities._open_marketing_activities_page",
        lambda page, account_id, account=None: True,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activities._activity_search_input_locator",
        lambda page: None,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activities._read_activity_search_input_value",
        lambda page: "20981",
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activity_page_guard.ensure_marketing_activities_tab_focus",
        lambda page, account_id: {"focused": True, "url": page.url, "search_found": True},
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activity_page_guard.wait_for_activity_search_input",
        lambda page, account_id, timeout=20: {
            "ready": True,
            "found": True,
            "search_input": {"found": True, "placeholder": "输入活动名称或ID搜索，多个ID以逗号隔开"},
        },
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activity_page_guard.prepare_marketing_activities_page_after_open",
        lambda page, account_id, wait_timeout=20: {"ready": True, "wait": {"found": True}},
    )

    page = FakeDpPage(
        body_text="营销活动 活动大厅 我能参加的活动 全部活动 营销活动报名",
        search_found=True,
    )
    result = search_marketing_activity_guarded(page, "store_A", "20981")
    assert result["status"] == "success"
    assert result.get("guarded") is True
    assert result["activity_id"] == "20981"


def test_search_marketing_activity_guarded_waits_when_input_missing(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activities._open_marketing_activities_page",
        lambda page, account_id, account=None: True,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activity_page_guard.ensure_marketing_activities_tab_focus",
        lambda page, account_id: {"focused": True, "url": page.url},
    )

    wait_calls: list[int] = []

    def fake_wait(page, account_id, timeout=20):
        wait_calls.append(timeout)
        return {
            "ready": False,
            "found": False,
            "search_input": {"found": False, "reason": "search_input_not_found"},
        }

    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activity_page_guard.wait_for_activity_search_input",
        fake_wait,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.campaign.marketing_activity_page_guard.prepare_marketing_activities_page_after_open",
        lambda page, account_id, wait_timeout=20: {"ready": False},
    )

    page = FakeDpPage(
        url="about:blank",
        body_text="",
        search_found=False,
    )
    result = search_marketing_activity_guarded(page, "store_A", "20981")
    assert result["status"] == "failed"
    assert result["step"] == "find_search_input"
    assert result.get("guarded") is True
    assert wait_calls


def test_register_marketing_activity_guarded_restores_original_search(monkeypatch):
    import pdd_agent.skills.campaign.marketing_activities as ma

    original_search = ma.search_marketing_activity
    patched_during_register: list[bool] = []

    def fake_register(page, account_id, activity_id, pdd_product_ids=None, account=None):
        patched_during_register.append(
            ma.search_marketing_activity is search_marketing_activity_guarded
        )
        return {"status": "success", "step": "register_completed", "activity_id": activity_id}

    monkeypatch.setattr(ma, "register_marketing_activity", fake_register)

    page = FakeDpPage()
    result = register_marketing_activity_guarded(
        page,
        "store_A",
        "20981",
        pdd_product_ids=["974453800119"],
    )
    assert patched_during_register == [True]
    assert result["status"] == "success"
    assert result.get("guarded_register") is True
    assert ma.search_marketing_activity is original_search

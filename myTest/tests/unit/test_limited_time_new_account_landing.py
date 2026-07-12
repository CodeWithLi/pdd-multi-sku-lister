"""新号限时限量购落地页兜底 — 单元测试。"""

from unittest.mock import MagicMock

from pdd_agent.skills.campaign.limited_time_click_create_bridge import (
    click_create_entering_activity_settings,
)
from pdd_agent.skills.campaign.limited_time_new_account_landing import (
    detect_new_account_limited_time_landing,
    is_new_account_limited_time_landing_page,
)


class FakeDpPage:
    def __init__(self, *, js_results: list | None = None, url: str = ""):
        self._js_results = list(js_results or [])
        self.url = url

    def run_js(self, _script: str):
        if self._js_results:
            return self._js_results.pop(0)
        return {"match": False, "reason": "not_new_account_landing"}


def test_detect_new_account_landing_match():
    page = FakeDpPage(js_results=[{"match": True, "reason": "no_current_activity_button"}])
    result = detect_new_account_limited_time_landing(page)
    assert result["match"] is True


def test_detect_new_account_landing_legacy_page():
    page = FakeDpPage(js_results=[{"match": False, "reason": "legacy_ele_create_button"}])
    assert detect_new_account_limited_time_landing(page)["reason"] == "legacy_ele_create_button"


def test_bridge_skips_when_already_on_activity_settings():
    page = FakeDpPage()
    wait = MagicMock(return_value=True)
    legacy = MagicMock(return_value=False)

    assert click_create_entering_activity_settings(
        page,
        "acc1",
        legacy_click_create=legacy,
        wait_activity_settings=wait,
    )

    wait.assert_called_once()
    legacy.assert_not_called()


def test_bridge_uses_new_account_flow_when_detected():
    page = FakeDpPage(
        js_results=[
            {"match": True, "reason": "no_current_activity_button"},
        ]
    )
    wait = MagicMock(side_effect=[False, True])
    legacy = MagicMock(return_value=False)

    def _fake_new_click(_page, account_id, **kwargs):
        assert account_id == "acc1"
        return True

    import pdd_agent.skills.campaign.limited_time_click_create_bridge as bridge

    original = bridge.click_new_account_landing_create
    bridge.click_new_account_landing_create = _fake_new_click
    try:
        assert click_create_entering_activity_settings(
            page,
            "acc1",
            legacy_click_create=legacy,
            wait_activity_settings=wait,
        )
    finally:
        bridge.click_new_account_landing_create = original

    legacy.assert_not_called()
    assert wait.call_count == 2


def test_bridge_falls_back_to_legacy_for_old_accounts():
    page = FakeDpPage(
        js_results=[
            {"match": False, "reason": "legacy_activity_product_tabs"},
        ]
    )
    wait = MagicMock(return_value=False)
    legacy = MagicMock(return_value=True)

    assert click_create_entering_activity_settings(
        page,
        "acc1",
        legacy_click_create=legacy,
        wait_activity_settings=wait,
    )

    legacy.assert_called_once_with(page, "acc1")


def test_is_new_account_landing_page_true():
    page = FakeDpPage(js_results=[{"match": True, "reason": "history_activity_empty_landing"}])
    assert is_new_account_limited_time_landing_page(page) is True

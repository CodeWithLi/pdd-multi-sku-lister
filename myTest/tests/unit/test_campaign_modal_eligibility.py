"""搜索弹窗商品可报名性检测。"""

from types import SimpleNamespace

from pdd_agent.skills.campaign.marketing_activities import (
    _ensure_modal_eligible_tab,
    _format_modal_eligibility_failure,
    _modal_search_results_loading,
    _wait_modal_products_loaded,
)


class FakeModal:
    def __init__(self, *, evaluate_results: list | None = None, row_count: int = 0):
        self._results = list(evaluate_results or [])
        self._row_count = row_count
        self.page = SimpleNamespace(
            evaluate=self.evaluate,
            mouse=SimpleNamespace(click=lambda *_args, **_kwargs: None),
        )

    def evaluate(self, script: str, *args):
        if self._results:
            return self._results.pop(0)
        if "加载中" in script or "正在加载" in script:
            return False
        if "可报名" in script and "不可报名" in script:
            return {"switched": True, "tab_text": "可报名商品"}
        if "click_points" in script:
            return {
                "click_points": [{"id": "967058176181", "x": 120, "y": 240}],
                "row_count": 1,
            }
        if "need_select_warning" in script:
            return {"has_table": True, "body_checked": 1, "selected": True, "need_select_warning": False}
        return {}

    def locator(self, selector: str):
        return SimpleNamespace(count=lambda: self._row_count)


def test_format_time_requirement_failure():
    eligibility = {
        "eligible_ids": ["965182969751"],
        "time_blocked": [
            {
                "product_id": "966631777744",
                "reason_text": "该商品近期有更新规格，需等待1天后才可报名",
            }
        ],
        "missing_ids": ["966631777744"],
    }
    result = _format_modal_eligibility_failure(eligibility, ["965182969751", "966631777744"])
    assert result["step"] == "product_time_requirement_not_met"
    assert result["error"] == "商品需过24h后才可以报活动"
    assert "未满足时间要求" not in result["error"]


def test_format_partial_ineligible_failure():
    eligibility = {
        "eligible_ids": ["965182969751", "962138900436"],
        "time_blocked": [],
        "other_ineligible": [],
        "missing_ids": ["966631777744"],
    }
    result = _format_modal_eligibility_failure(
        eligibility,
        ["965182969751", "962138900436", "966631777744"],
    )
    assert result["step"] == "product_not_eligible_for_activity"
    assert "不可报名" in result["error"]
    assert "966631777744" in result["error"]


def test_format_all_eligible_returns_empty():
    eligibility = {
        "eligible_ids": ["111", "222"],
        "time_blocked": [],
        "missing_ids": [],
    }
    assert _format_modal_eligibility_failure(eligibility, ["111", "222"]) == {}


def test_wait_modal_products_loaded_waits_until_rows_visible(monkeypatch):
    from pdd_agent.skills.campaign import marketing_activities as mod

    calls = {"count": 0}

    def fake_scan(_modal, product_ids):
        calls["count"] += 1
        if calls["count"] >= 2:
            return {
                "found_ids": product_ids,
                "row_count": 1,
                "table_count": 1,
                "detection_methods": {"row_match": product_ids},
            }
        return {"found_ids": [], "row_count": 0, "table_count": 0, "detection_methods": {}}

    monkeypatch.setattr(mod, "_scan_modal_products", fake_scan)
    monkeypatch.setattr(mod, "_ensure_modal_eligible_tab", lambda _modal: {"switched": True})
    monkeypatch.setattr(mod, "_modal_search_results_loading", lambda _modal: False)
    monkeypatch.setattr(mod, "time", SimpleNamespace(sleep=lambda *_args, **_kwargs: None))

    modal = FakeModal(row_count=1)
    result = _wait_modal_products_loaded(modal, ["965182969751"], timeout=3)

    assert result["loaded"] is True
    assert result["eligible_ids"] == ["965182969751"]
    assert calls["count"] >= 2


def test_ensure_modal_eligible_tab_returns_switch_result():
    modal = FakeModal(evaluate_results=[{"switched": True, "tab_text": "可报名商品"}])
    assert _ensure_modal_eligible_tab(modal)["switched"] is True


def test_modal_search_results_loading_detects_spinner():
    modal = FakeModal(evaluate_results=[True, False])
    assert _modal_search_results_loading(modal) is True
    assert _modal_search_results_loading(modal) is False


def test_scan_modal_products_uses_page_evaluate(monkeypatch):
    from pdd_agent.skills.campaign import marketing_activities as mod

    captured: dict[str, object] = {}

    class Page:
        def evaluate(self, script, ids):
            captured["ids"] = ids
            return {
                "found_ids": ids,
                "row_count": 1,
                "table_count": 1,
                "detection_methods": {"row_match": ids},
            }

    modal = FakeModal()
    modal.page = Page()
    result = mod._scan_modal_products(modal, ["965182969751"])
    assert result["found_ids"] == ["965182969751"]
    assert captured["ids"] == ["965182969751"]

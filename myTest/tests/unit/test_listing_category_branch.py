from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing import upload as listing_upload


def _page_with_text(text: str) -> MagicMock:
    page = MagicMock()
    page.run_js.return_value = text
    page.ele.return_value = None
    return page


def test_category_page_needs_manual_selection_when_no_recommendation():
    page = _page_with_text("暂无推荐的分类，点击手动选择分类")
    page.ele.side_effect = lambda locator, **kwargs: MagicMock() if locator == "text:选择分类" else None
    assert listing_upload._category_page_needs_manual_selection(page) is True


def test_category_page_needs_manual_selection_when_recommended():
    page = _page_with_text(
        "玩具/童车/益智/积木/模型 > 毛绒布艺类玩具 > 毛绒公仔/玩偶\n手动选择商品分类"
    )
    assert listing_upload._category_page_needs_manual_selection(page) is False


def test_select_category_by_keyword_search_clicks_first_result(monkeypatch):
    page = MagicMock()
    search_input = MagicMock()
    first_cat = MagicMock()

    def fake_ele(locator, **kwargs):
        if 'placeholder="请输入关键词搜索分类"' in locator:
            return search_input
        if "SPP_searchItem" in locator:
            return first_cat
        return None

    page.ele.side_effect = fake_ele
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    ok = listing_upload._select_category_by_keyword_search(page, "store_A", "BD001", "玩偶")

    assert ok is True
    search_input.input.assert_called_once_with("玩偶", clear=True)
    page.run_js.assert_called()


def test_open_category_selector_panel_clicks_button(monkeypatch):
    page = MagicMock()
    btn = MagicMock()
    page.ele.return_value = btn
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._open_category_selector_panel(page) is True
    page.run_js.assert_called_once()

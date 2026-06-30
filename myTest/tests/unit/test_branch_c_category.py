"""分支 C 商品分类页逻辑测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing import upload as listing_upload


def test_category_already_selected_skips_manual(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = True
    page.ele.return_value = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_category_page_body_text",
        lambda _page: "商品分类\n文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋",
    )

    assert listing_upload._branch_c_category_already_selected(page) is True
    assert listing_upload._category_page_needs_manual_selection(page) is False


def test_pencil_case_recommendation_does_not_open_manual_selector(monkeypatch):
    """笔袋类推荐类目已展示时不应误点「选择分类」。"""
    page = MagicMock()
    page.run_js.return_value = False
    next_btn = MagicMock()

    def _ele(locator, timeout=1):
        if locator in ("#bottomSubmitBtnId", "text:下一步"):
            return next_btn
        if locator == "text:选择分类":
            return MagicMock()
        return None

    page.ele.side_effect = _ele
    monkeypatch.setattr(
        listing_upload,
        "_category_page_body_text",
        lambda _page: "商品分类\n文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋",
    )

    assert listing_upload._branch_c_category_already_selected(page) is True
    assert listing_upload._category_page_needs_manual_selection(page) is False


def test_no_recommendation_still_needs_manual(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = False
    page.ele.return_value = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_category_page_body_text",
        lambda _page: "暂无推荐的分类\n选择分类",
    )

    assert listing_upload._branch_c_category_already_selected(page) is False
    assert listing_upload._category_page_needs_manual_selection(page) is True


def test_click_category_next_step_uses_mouse_fallback(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_mouse_click_category_next_button",
        lambda *_a, **_k: (True, "mouse/#bottomSubmitBtnId"),
    )
    monkeypatch.setattr(listing_upload, "_click_branch_c_category_recommendation", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._click_category_next_step(page, ui_type="C", account_id="store_A", label="BD050B") is True


def test_click_category_next_step_prefers_mouse_click(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_mouse_click_category_next_button",
        lambda *_a, **_k: (True, "mouse/#bottomSubmitBtnId"),
    )
    monkeypatch.setattr(listing_upload, "_click_branch_c_category_recommendation", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._click_category_next_step(page, ui_type="C", account_id="store_A", label="BD050B") is True


def test_wait_for_category_section_ready_waits_then_succeeds(monkeypatch):
    page = MagicMock()
    checks = iter([False, False, True])
    monkeypatch.setattr(
        listing_upload,
        "_category_section_is_ready",
        lambda _page: next(checks, True),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda s: sleeps.append(s)))

    assert listing_upload._wait_for_category_section_ready(page, "store_A", "BD050B", max_wait=10) is True
    assert len(sleeps) == 2


def test_category_section_ready_when_recommendation_cards_visible(monkeypatch):
    page = MagicMock()
    page.run_js.side_effect = [
        "商品分类\n文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋",
        True,
    ]
    assert listing_upload._category_section_is_ready(page) is True


def test_wait_for_category_page_advance_skips_when_already_left(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_is_still_on_category_publish_step",
        lambda _page: False,
    )
    slept = MagicMock()
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=slept))

    assert listing_upload._wait_for_category_page_advance(page, "store_A", "BD050B") is True
    slept.assert_not_called()


def test_wait_for_category_page_advance_waits_until_jump(monkeypatch):
    page = MagicMock()
    states = iter([True, True, False])
    monkeypatch.setattr(
        listing_upload,
        "_is_still_on_category_publish_step",
        lambda _page: next(states, False),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda s: sleeps.append(s)))

    assert listing_upload._wait_for_category_page_advance(
        page, "store_A", "BD050B", max_wait=30
    ) is True
    assert len(sleeps) == 2


def test_click_category_next_step_burst_clicks_extra_when_still_on_page(monkeypatch):
    page = MagicMock()
    click_count = {"n": 0}
    category_clicks = {"n": 0}

    def _click(*_a, **_k):
        click_count["n"] += 1
        return True

    def _mouse_click(*_a, **_k):
        click_count["n"] += 1
        return True, "mouse"

    states = iter([True, True, True, False])
    monkeypatch.setattr(listing_upload, "_wait_category_submit_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "_click_category_next_step", _click)
    monkeypatch.setattr(listing_upload, "_mouse_click_category_next_button", _mouse_click)
    monkeypatch.setattr(
        listing_upload,
        "_click_branch_c_category_recommendation",
        lambda *_a, **_k: category_clicks.__setitem__("n", category_clicks["n"] + 1) or True,
    )
    monkeypatch.setattr(
        listing_upload,
        "_is_still_on_category_publish_step",
        lambda _page: next(states, False),
    )
    monkeypatch.setattr(listing_upload, "random", MagicMock(randint=lambda _a, _b: 3))
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._click_category_next_step_burst(page, account_id="store_A", label="BD050B") is True
    assert click_count["n"] == 3
    assert category_clicks["n"] == 2


def test_click_category_next_step_burst_skips_extra_when_advanced(monkeypatch):
    page = MagicMock()
    click_count = {"n": 0}
    monkeypatch.setattr(
        listing_upload,
        "_click_category_next_step",
        lambda *_a, **_k: click_count.__setitem__("n", click_count["n"] + 1) or True,
    )
    monkeypatch.setattr(listing_upload, "_is_still_on_category_publish_step", lambda _page: False)
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._click_category_next_step_burst(page, account_id="store_A", label="BD050B") is True
    assert click_count["n"] == 1


def test_branch_c_carousel_upload_count_parses_text(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = [3, 10]
    assert listing_upload._branch_c_carousel_upload_count(page) == (3, 10)


def test_click_branch_c_publish_tab_success(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = True
    slept: list[float] = []
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda s: slept.append(s)))

    assert listing_upload._click_branch_c_publish_tab(
        page, "以图发品", account_id="store_A", label="BD047A"
    ) is True
    assert slept


def test_upload_category_branch_c_covers_raises_when_both_paths_fail(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_ensure_branch_c_covers_on_image_tab",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        listing_upload,
        "_branch_c_search_publish_and_select",
        lambda *_a, **_k: False,
    )

    try:
        listing_upload._upload_category_branch_c_covers(
            page,
            "store_A",
            {"category_keyword": "笔袋"},
            {"category_keyword": "笔袋", "title": "测试标题"},
            ["/tmp/cover.jpg"],
            label="BD047A",
        )
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "搜索发品" in str(exc)

    assert raised


def test_upload_category_branch_c_covers_applies_title_after_upload(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_ensure_branch_c_covers_on_image_tab",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        listing_upload,
        "apply_title_after_cover_upload",
        lambda *_a, **_k: "AI标题",
    )
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))
    monkeypatch.setattr(listing_upload, "random", MagicMock(uniform=lambda *_: 1.0))

    title = listing_upload._upload_category_branch_c_covers(
        page,
        "store_A",
        {"title_mode": "page_ai"},
        {"title": "fallback"},
        ["/tmp/cover.jpg"],
        label="BD047A",
    )
    assert title == "AI标题"

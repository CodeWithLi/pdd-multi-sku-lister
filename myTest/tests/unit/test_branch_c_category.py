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
        "_click_branch_c_category_next",
        lambda *_a, **_k: (True, "e2e-publish-button"),
    )
    monkeypatch.setattr(listing_upload, "_click_branch_c_category_recommendation", lambda *_a, **_k: True)
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._click_category_next_step(page, ui_type="C", account_id="store_A", label="BD050B") is True


def test_click_category_next_step_prefers_mouse_click(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_click_branch_c_category_next",
        lambda *_a, **_k: (True, "e2e-publish-button"),
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
    monkeypatch.setattr(listing_upload, "_click_branch_c_category_next", _mouse_click)
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
    monkeypatch.setattr(
        listing_upload,
        "_handle_image_category_recommendation_modal",
        lambda *_a, **_k: False,
    )
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


def test_upload_category_branch_c_covers_skips_page_ai_on_category_page(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_ensure_branch_c_covers_on_image_tab",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        listing_upload,
        "apply_title_after_branch_c_cover_upload",
        lambda *_a, **_k: "fallback",
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
    assert title == "fallback"


def test_read_branch_c_cover_upload_error_detects_dimension_message(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "read_pdd_image_file_size_error",
        lambda _page: "",
    )
    monkeypatch.setattr(
        listing_upload,
        "read_pdd_image_dimension_error",
        lambda _page: "尺寸不符合要求",
    )
    assert listing_upload._read_branch_c_cover_upload_error(page) == "尺寸不符合要求"


def test_read_branch_c_cover_upload_error_detects_file_size_message(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "read_pdd_image_file_size_error",
        lambda _page: "上传图片大小不能超过 3MB",
    )
    assert listing_upload._read_branch_c_cover_upload_error(page) == "上传图片大小不能超过 3MB"


def test_raise_if_branch_c_cover_upload_rejected_raises(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        "pdd_agent.skills.listing.pdd_page_image_errors.read_pdd_image_file_size_error",
        lambda _page: "",
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.pdd_page_image_errors.read_pdd_image_dimension_error",
        lambda _page: "尺寸不符合要求",
    )
    try:
        listing_upload._raise_if_branch_c_cover_upload_rejected(
            page, account_id="store_A", label="BD047A"
        )
        raised = False
    except listing_upload.BranchCCoverImageRejected as exc:
        raised = True
        assert exc.platform_message == "尺寸不符合要求"

    assert raised


def test_upload_branch_c_cover_files_stops_on_dimension_error(monkeypatch):
    page = MagicMock()
    cover_input = MagicMock()
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))
    monkeypatch.setattr(
        listing_upload,
        "_raise_if_branch_c_cover_upload_rejected",
        lambda *_a, **_k: (_ for _ in ()).throw(
            listing_upload.BranchCCoverImageRejected("尺寸不符合要求", platform_message="尺寸不符合要求")
        ),
    )

    try:
        listing_upload._upload_branch_c_cover_files(
            page,
            cover_input,
            ["/tmp/cover.jpg"],
            account_id="store_A",
            label="BD047A",
            wait_seconds=2,
        )
        raised = False
    except listing_upload.BranchCCoverImageRejected:
        raised = True

    assert raised
    cover_input.input.assert_called_once()


def test_image_category_recommendation_modal_visible(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = {"visible": True, "hasRoot": True}
    assert listing_upload._is_image_category_recommendation_modal_visible(page) is True


def test_image_category_recommendation_modal_not_visible(monkeypatch):
    page = MagicMock()
    page.run_js.side_effect = [
        {"visible": False, "hasRoot": False},
        "商品分类 笔袋",
    ]
    assert listing_upload._is_image_category_recommendation_modal_visible(page) is False


def test_handle_image_category_recommendation_modal_selects_first_and_confirms(monkeypatch):
    page = MagicMock()
    visible = iter([True, False])

    def _visible(_page):
        return next(visible, False)

    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_modal.is_image_category_recommendation_modal_visible",
        _visible,
    )
    monkeypatch.setattr(
        "pdd_agent.skills.listing.category_branch_c_modal._attempt_close_recommendation_modal",
        lambda *_a, **_k: (True, "文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋"),
    )
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._handle_image_category_recommendation_modal(
        page, "store_A", "BD050B"
    ) is True


def test_handle_image_category_recommendation_modal_absent_returns_false(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = {"visible": False}

    assert listing_upload._handle_image_category_recommendation_modal(
        page, "store_A", "BD050B"
    ) is False


def test_branch_c_not_selected_when_recommendation_modal_open(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_is_image_category_recommendation_modal_visible",
        lambda _page: True,
    )
    monkeypatch.setattr(
        listing_upload,
        "_category_page_body_text",
        lambda _page: "根据您上传的图片 为您推荐分类 请选择",
    )

    assert listing_upload._branch_c_category_already_selected(page) is False
    assert listing_upload._category_page_needs_manual_selection(page) is False


def test_branch_c_selected_with_category_picker_uses_direct_next(monkeypatch):
    """三级列选器已展示「已选分类」时不应误判为 manual_picker。"""
    page = MagicMock()
    page.run_js.return_value = True
    next_btn = MagicMock()

    def _ele(locator, timeout=1):
        if locator in ("#bottomSubmitBtnId", "text:下一步"):
            return next_btn
        return None

    page.ele.side_effect = _ele
    monkeypatch.setattr(
        listing_upload,
        "_is_image_category_recommendation_modal_visible",
        lambda _page: False,
    )
    monkeypatch.setattr(
        listing_upload,
        "_category_page_body_text",
        lambda _page: (
            "商品分类\n分类选择\n"
            "已选分类 文具电教/文化用品/商务用品 > 日常学习用品 > 笔袋/文具袋\n"
            "下一步，完善商品信息"
        ),
    )

    assert listing_upload._branch_c_category_already_selected(page) is True
    assert listing_upload._category_page_is_manual_picker(page, "C") is False
    assert listing_upload._resolve_category_page_mode(page, "C", manual_category=False) == "direct_next"


def test_click_branch_c_recommendation_skips_when_category_selected(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_handle_image_category_recommendation_modal",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        listing_upload,
        "_branch_c_category_already_selected",
        lambda _page: True,
    )
    clicks = {"js": 0}
    page.run_js.side_effect = lambda *_a, **_k: clicks.__setitem__("js", clicks["js"] + 1)

    assert listing_upload._click_branch_c_category_recommendation(page, "store_A", "BD050B") is False
    assert clicks["js"] == 0


def test_click_branch_c_recommendation_prefers_modal_handler(monkeypatch):
    page = MagicMock()
    calls = {"modal": 0, "inline": 0}

    monkeypatch.setattr(
        listing_upload,
        "_handle_image_category_recommendation_modal",
        lambda *_a, **_k: calls.__setitem__("modal", calls["modal"] + 1) or True,
    )
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._click_branch_c_category_recommendation(page, "store_A", "BD050B") is True
    assert calls["modal"] == 1

"""页面 AI 标题（立即使用 / AI生成）测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing import page_ai_title


def test_try_click_ai_generate_returns_title(monkeypatch):
    page = MagicMock()
    btn = MagicMock()
    page.ele.return_value = btn

    reads = iter(["", "", "爱心绣花笔袋轻盈便携"])
    monkeypatch.setattr(page_ai_title, "_read_title_from_input", lambda _page: next(reads, "爱心绣花笔袋轻盈便携"))
    monkeypatch.setattr(page_ai_title, "time", MagicMock(sleep=lambda *_: None))

    title = page_ai_title._try_click_ai_generate_title(page, "store_A")
    assert title == "爱心绣花笔袋轻盈便携"
    btn.click.assert_called_once()


def test_wait_and_apply_falls_back_to_ai_generate(monkeypatch):
    page = MagicMock()
    page.ele.return_value = None

    calls = iter(["", "AI推荐标题"])
    monkeypatch.setattr(page_ai_title, "_read_title_from_input", lambda _page: next(calls, "AI推荐标题"))
    monkeypatch.setattr(page_ai_title, "_find_use_now_button", lambda _page: None)
    monkeypatch.setattr(page_ai_title, "_click_use_now_via_js", lambda _page: False)
    monkeypatch.setattr(
        page_ai_title,
        "_try_click_ai_generate_title",
        lambda _page, _aid: "AI推荐标题",
    )
    monkeypatch.setattr(page_ai_title, "time", MagicMock(sleep=lambda *_: None))

    title = page_ai_title.wait_and_apply_page_ai_title(
        page,
        "store_A",
        initial_wait=0,
        max_wait=3,
    )
    assert title == "AI推荐标题"


def test_apply_title_skips_wait_when_title_exists(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        page_ai_title,
        "is_page_ai_title_mode",
        lambda _info: True,
    )
    monkeypatch.setattr(
        page_ai_title,
        "_read_title_from_input",
        lambda _page: "爱心绣花笔袋轻盈便携",
    )
    waited = MagicMock()
    monkeypatch.setattr(page_ai_title, "wait_and_apply_page_ai_title", waited)

    title = page_ai_title.apply_title_after_cover_upload(page, "store_A", {})
    assert title == "爱心绣花笔袋轻盈便携"
    waited.assert_not_called()

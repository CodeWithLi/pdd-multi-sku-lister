"""详情页轮播图补传 guard 测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing import listing_detail_carousel_guard as guard


def test_parse_detail_page_carousel_progress():
    assert guard.parse_detail_page_carousel_progress("已上传0/10张，拖拽可调整顺序") == (0, 10)
    assert guard.parse_detail_page_carousel_progress("已上传 3 / 10 张") == (3, 10)
    assert guard.parse_detail_page_carousel_progress("无轮播信息") is None


def test_count_detail_page_carousel_images_from_js():
    page = MagicMock()
    page.run_js.return_value = [2, 10]
    assert guard.count_detail_page_carousel_images(page) == (2, 10)


def test_is_detail_page_carousel_missing():
    page = MagicMock()
    page.run_js.return_value = [0, 10]
    assert guard.is_detail_page_carousel_missing(page) is True
    page.run_js.return_value = [1, 10]
    assert guard.is_detail_page_carousel_missing(page) is False


def test_ensure_detail_page_carousel_before_title_skips_when_present(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = [3, 10]
    called = {"upload": False}

    def _fail_upload(*_args, **_kwargs):
        called["upload"] = True
        return False

    monkeypatch.setattr(guard, "_upload_detail_page_carousel_files", _fail_upload)

    ok = guard.ensure_detail_page_carousel_before_title(
        page,
        ["/tmp/1.png", "/tmp/2.png"],
        account_id="store_A",
        label="BD105A/第一套图",
    )
    assert ok is True
    assert called["upload"] is False


def test_ensure_detail_page_carousel_before_title_uploads_when_missing(monkeypatch):
    page = MagicMock()
    counts = iter([[0, 10], [0, 10], [2, 10]])
    page.run_js.side_effect = lambda *_a, **_k: next(counts, [2, 10])

    monkeypatch.setattr(guard, "time", MagicMock(sleep=lambda *_: None))
    monkeypatch.setattr(guard, "_reveal_detail_page_carousel_section", lambda *_: None)
    monkeypatch.setattr(guard, "_find_detail_page_carousel_input", lambda *_: MagicMock())
    monkeypatch.setattr(
        guard,
        "_upload_detail_page_carousel_files",
        lambda *_a, **_k: True,
    )

    ok = guard.ensure_detail_page_carousel_before_title(
        page,
        [f"/tmp/{i}.png" for i in range(1, 6)],
        account_id="store_A",
        label="BD105A/第一套图",
    )
    assert ok is True

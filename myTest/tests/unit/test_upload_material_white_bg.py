"""商品素材白底图：删除平台自动生成图后再上传本地 9.png。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing import upload as listing_upload


def test_product_material_has_existing_image_true(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = True

    assert listing_upload._product_material_has_existing_image(page) is True
    page.run_js.assert_called_once()


def test_product_material_has_existing_image_false_on_error(monkeypatch):
    page = MagicMock()
    page.run_js.side_effect = RuntimeError("disconnect")

    assert listing_upload._product_material_has_existing_image(page) is False


def test_delete_existing_product_material_image_waits_until_cleared(monkeypatch):
    page = MagicMock()
    page.run_js.side_effect = [True, None, None]
    checks = iter([True, True, False])
    monkeypatch.setattr(
        listing_upload,
        "_product_material_has_existing_image",
        lambda _page: next(checks, False),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda s: sleeps.append(s)))

    assert listing_upload._delete_existing_product_material_image(
        page, "store_A", "BD046A/第一套"
    ) is True
    assert len(sleeps) == 3


def test_delete_existing_product_material_image_not_clicked(monkeypatch):
    page = MagicMock()
    page.run_js.return_value = False

    assert listing_upload._delete_existing_product_material_image(
        page, "store_A", "BD046A/第一套"
    ) is False


def test_upload_product_material_deletes_existing_before_input(monkeypatch):
    page = MagicMock()
    material_input = MagicMock()
    monkeypatch.setattr(
        listing_upload,
        "_product_material_has_existing_image",
        lambda _page: True,
    )
    monkeypatch.setattr(
        listing_upload,
        "_delete_existing_product_material_image",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        listing_upload,
        "_click_product_material_local_upload",
        lambda _page: True,
    )
    monkeypatch.setattr(
        listing_upload,
        "_find_product_material_upload_input",
        lambda _page: material_input,
    )
    monkeypatch.setattr(
        listing_upload,
        "raise_if_pdd_image_upload_rejected",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    assert listing_upload._upload_product_material_image(
        page, "store_A", "BD046A/第一套", "D:/9.png"
    ) is True
    material_input.input.assert_called_once_with("D:/9.png")


def test_upload_product_material_skips_delete_when_empty(monkeypatch):
    page = MagicMock()
    material_input = MagicMock()
    delete_mock = MagicMock(return_value=True)
    monkeypatch.setattr(
        listing_upload,
        "_product_material_has_existing_image",
        lambda _page: False,
    )
    monkeypatch.setattr(
        listing_upload,
        "_delete_existing_product_material_image",
        delete_mock,
    )
    monkeypatch.setattr(
        listing_upload,
        "_find_product_material_upload_input",
        lambda _page: material_input,
    )
    monkeypatch.setattr(
        listing_upload,
        "raise_if_pdd_image_upload_rejected",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(listing_upload, "time", MagicMock(sleep=lambda *_: None))

    listing_upload._upload_product_material_image(page, "store_A", "BD046A/第一套", "D:/9.png")

    delete_mock.assert_not_called()
    material_input.input.assert_called_once_with("D:/9.png")

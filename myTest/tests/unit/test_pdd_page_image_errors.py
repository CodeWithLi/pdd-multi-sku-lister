"""拼多多页面图片尺寸报错检测测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing import upload as listing_upload
from pdd_agent.skills.listing import multi_spec_page
from pdd_agent.skills.listing.pdd_page_image_errors import (
    PddImageDimensionRejected,
    read_pdd_image_dimension_error,
    raise_if_pdd_image_dimension_rejected,
)


def test_read_pdd_image_dimension_error_from_toast():
    page = MagicMock()
    page.run_js.return_value = "尺寸不符合要求"
    assert read_pdd_image_dimension_error(page) == "尺寸不符合要求"


def test_raise_if_preview_dimension_rejected():
    page = MagicMock()
    page.run_js.return_value = "尺寸不符合要求"
    try:
        raise_if_pdd_image_dimension_rejected(
            page,
            account_id="store_A",
            label="蓝色 / 笔袋",
            image_kind="preview",
            sku_label="蓝色 / 笔袋",
        )
        raised = False
    except PddImageDimensionRejected as exc:
        raised = True
        assert exc.image_kind == "preview"
        assert exc.sku_label == "蓝色 / 笔袋"

    assert raised


def test_upload_row_preview_stops_on_dimension_error(monkeypatch):
    page = MagicMock()
    upload_input = MagicMock()
    monkeypatch.setattr(multi_spec_page, "_now", lambda: 0.0)
    monkeypatch.setattr(multi_spec_page, "_log_step", lambda *_a, **_k: None)
    monkeypatch.setattr(
        multi_spec_page,
        "_preview_is_uploaded",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        multi_spec_page,
        "_resolve_preview_upload_input",
        lambda *_a, **_k: upload_input,
    )
    monkeypatch.setattr(multi_spec_page, "time", MagicMock(sleep=lambda *_: None))

    def _raise(*_a, **_k):
        raise PddImageDimensionRejected(
            "preview rejected",
            platform_message="尺寸不符合要求",
            image_kind="preview",
            sku_label="蓝色 / 笔袋",
        )

    monkeypatch.setattr(multi_spec_page, "raise_if_pdd_image_dimension_rejected", _raise)

    try:
        multi_spec_page.upload_row_preview(
            page,
            0,
            "/tmp/preview.png",
            "store_A",
            "蓝色 / 笔袋",
        )
        raised = False
    except PddImageDimensionRejected:
        raised = True

    assert raised
    upload_input.input.assert_called_once()


def test_branch_c_wrapper_still_raises(monkeypatch):
    page = MagicMock()
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

"""按规格编码上传预览图封装测试。"""

from pathlib import Path

import pytest

from pdd_agent.domain.models import SkuCombo
from pdd_agent.skills.listing.listing_spec_code_preview_upload import (
    build_spec_code_preview_items,
    normalize_spec_code,
    upload_previews_by_spec_code,
)


def test_normalize_spec_code_strips_and_uppercases():
    assert normalize_spec_code(" bd062a+YKL004L ") == "BD062A+YKL004L"
    assert normalize_spec_code("BD351M+PS004A小白笔*4") == "BD351M+PS004A小白笔*4"


def test_build_spec_code_preview_items_uses_combo_folder(tmp_path: Path):
    img_a = tmp_path / "BD062A+YKL020A.jpg"
    img_b = tmp_path / "BD062A+YKL007P.jpg"
    img_a.write_bytes(b"a")
    img_b.write_bytes(b"b")
    skus = [
        SkuCombo(
            style_code="BD062A",
            style_name="白色",
            model_code="YKL020A",
            model_name="薄荷-夏风",
            combo_folder="BD062A+YKL020A",
            preview_image=img_a,
        ),
        SkuCombo(
            style_code="BD062A",
            style_name="白色",
            model_code="YKL007P",
            model_name="薄荷-挂件",
            combo_folder="BD062A+YKL007P",
            preview_image=img_b,
        ),
    ]
    items = build_spec_code_preview_items(skus)
    assert len(items) == 2
    assert items[0].spec_code == "BD062A+YKL020A"
    assert items[1].spec_code == "BD062A+YKL007P"
    assert items[0].image_path == img_a
    assert items[1].image_path == img_b


def test_build_spec_code_preview_items_dedupes_same_spec_code(tmp_path: Path):
    img = tmp_path / "BD062A.jpg"
    img.write_bytes(b"x")
    skus = [
        SkuCombo(
            style_code="BD062A",
            style_name="白色",
            model_code="BD062A",
            model_name="薄荷",
            combo_folder="BD062A",
            preview_image=img,
        ),
        SkuCombo(
            style_code="BD062A",
            style_name="白色",
            model_code="BD062A",
            model_name="薄荷",
            combo_folder="BD062A",
            preview_image=img,
        ),
    ]
    assert len(build_spec_code_preview_items(skus)) == 1


class _FakePage:
    def __init__(self, scripts: dict[str, object] | None = None):
        self.scripts = scripts or {}
        self.inputs: list[str] = []

    def run_js(self, script: str, *args):
        if "return JSON.stringify(map)" in script:
            return '{"BD062A+YKL020A":"BD062A+YKL020A"}'
        if "return JSON.stringify(hit || {found: false})" in script:
            return '{"found": true, "code": "BD062A+YKL020A", "uploaded": false}'
        if "return JSON.stringify({ready: true" in script:
            return '{"ready": true, "code": "BD062A+YKL020A"}'
        if "return false;" in script and "isPreviewCellUploaded" in script:
            return True
        return self.scripts.get(script)

    def ele(self, locator: str, timeout: float = 0.5):
        class _Input:
            def input(self, path: str):
                self.path = path

        if "data-pdd-preview-spec-code" in locator:
            inp = _Input()
            return inp
        return None


def test_upload_previews_by_spec_code_happy_path(tmp_path: Path):
    img = tmp_path / "BD062A+YKL020A.jpg"
    img.write_bytes(b"x")
    skus = [
        SkuCombo(
            style_code="BD062A",
            style_name="白色",
            model_code="YKL020A",
            model_name="薄荷-夏风",
            combo_folder="BD062A+YKL020A",
            preview_image=img,
        ),
    ]
    page = _FakePage()
    result = upload_previews_by_spec_code(
        page,
        "store_A",
        skus,
        prepare_table=False,
    )
    assert result.need_upload == 1
    assert result.uploaded == 1
    assert result.verified == 1
    assert not result.missing_codes

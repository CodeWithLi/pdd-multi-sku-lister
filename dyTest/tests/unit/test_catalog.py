"""catalog 单元测试。"""

from pathlib import Path

from dy_agent.skills.listing.catalog import build_listing_unit


def test_build_listing_unit_basic(tmp_path: Path):
    product_dir = tmp_path / "BD046A"
    product_dir.mkdir()
    (product_dir / "1.png").write_bytes(b"x")
    (product_dir / "2.png").write_bytes(b"x")
    (product_dir / "BD046A+MODEL1.png").write_bytes(b"x")

    unit = build_listing_unit("BD046A", "", product_dir, family_code="BD046")
    assert unit.product_code == "BD046A"
    assert len(unit.carousel_images) == 2
    assert len(unit.skus) == 1
    assert unit.skus[0].model_code == "MODEL1"


def test_build_listing_unit_parses_multi_accessory_combo_like_pdd(tmp_path: Path):
    product_dir = tmp_path / "BD021A卡皮巴拉笔袋"
    product_dir.mkdir()
    (product_dir / "1.png").write_bytes(b"x")
    (product_dir / "BD021A卡皮巴拉笔袋+YKL001A.png").write_bytes(b"x")
    (product_dir / "BD021A卡皮巴拉笔袋+YKL001A+YKL020A+YKL004N.png").write_bytes(b"x")

    unit = build_listing_unit("BD021A卡皮巴拉笔袋", "第一套图", product_dir, family_code="BD021")
    assert unit.style_codes == ["BD021A卡皮巴拉笔袋"]
    assert "YKL001A" in unit.model_codes
    assert "套装" in unit.model_codes
    assert all(sku.style_code == "BD021A卡皮巴拉笔袋" for sku in unit.skus)


def test_build_listing_unit_detail_and_material(tmp_path: Path):
    product_dir = tmp_path / "BD046A"
    product_dir.mkdir()
    for name in ("1.png", "6.png", "7.png", "8.png", "9.png"):
        (product_dir / name).write_bytes(b"x")

    unit = build_listing_unit("BD046A", "", product_dir, family_code="BD046")
    assert [p.name for p in unit.detail_images] == ["6.png", "7.png", "8.png"]
    assert unit.material_image is not None
    assert unit.material_image.name == "9.png"

"""catalog 单元测试（对齐拼多多：单款/组合/套装 + 同套图兄弟合并 + 多套图）。"""

from pathlib import Path

from dy_agent.core.config import PathsConfig, YamlSettings
from dy_agent.skills.listing.catalog import (
    build_listing_unit,
    list_local_listing_targets,
    resolve_listing_units,
)


def _touch_code_dir(code_dir: Path, *, specs: list[str], numbered: range = range(1, 6)) -> None:
    code_dir.mkdir(parents=True, exist_ok=True)
    for index in numbered:
        (code_dir / f"{index}.png").write_bytes(b"img")
    for name in specs:
        (code_dir / name).write_bytes(b"spec")


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
    (product_dir / "BD021A卡皮巴拉笔袋.png").write_bytes(b"x")
    (product_dir / "BD021A卡皮巴拉笔袋+YKL001A.png").write_bytes(b"x")
    (product_dir / "BD021A卡皮巴拉笔袋+YKL001A+YKL020A+YKL004N.png").write_bytes(b"x")

    unit = build_listing_unit("BD021A卡皮巴拉笔袋", "第一套图", product_dir, family_code="BD021")
    assert unit.style_codes == ["BD021A卡皮巴拉笔袋"]
    assert "YKL001A" in unit.model_codes
    assert "套装" in unit.model_codes
    assert any(sku.model_code == "BD021A卡皮巴拉笔袋" for sku in unit.skus)
    assert len(unit.skus) == 3
    assert all(sku.style_code == "BD021A卡皮巴拉笔袋" for sku in unit.skus)


def test_build_listing_unit_includes_solo_sku_without_plus(tmp_path: Path):
    product_dir = tmp_path / "BD021A卡皮巴拉笔袋"
    product_dir.mkdir()
    (product_dir / "1.png").write_bytes(b"x")
    (product_dir / "BD021A卡皮巴拉笔袋.jpg").write_bytes(b"solo")
    (product_dir / "BD021A卡皮巴拉笔袋+YKL001A.jpg").write_bytes(b"a")
    (product_dir / "BD021A卡皮巴拉笔袋+YKL004N.jpg").write_bytes(b"b")
    (product_dir / "BD021A卡皮巴拉笔袋+YKL020A.jpg").write_bytes(b"c")
    (product_dir / "BD021A卡皮巴拉笔袋+YKL001A+YKL020A+YKL004N.jpg").write_bytes(b"bundle")

    unit = build_listing_unit("BD021A卡皮巴拉笔袋", "第一套图", product_dir, family_code="BD021")
    assert len(unit.skus) == 5
    assert unit.skus[0].model_code == "BD021A卡皮巴拉笔袋"
    assert unit.skus[0].combo_folder == "BD021A卡皮巴拉笔袋"


def test_sibling_codes_merged_within_same_image_set_like_pdd(tmp_path: Path):
    """上架 A 时，同套图兄弟 B/C 的规格图合并进同一 ListingUnit（对齐拼多多）。"""
    set_dir = tmp_path / "BD046" / "第一套图"
    _touch_code_dir(
        set_dir / "BD046A",
        specs=["BD046A.png", "BD046A+AXBD001A.png"],
    )
    _touch_code_dir(
        set_dir / "BD046B",
        specs=["BD046B.png", "BD046B+AXBD001A.png"],
    )
    _touch_code_dir(
        set_dir / "BD046C",
        specs=["BD046C.png", "BD046C+AXBD001A.png"],
    )

    unit = build_listing_unit(
        "BD046A",
        "第一套图",
        set_dir / "BD046A",
        family_code="BD046",
    )
    assert unit.product_code == "BD046A"
    assert unit.family_code == "BD046"
    assert [sku.combo_folder for sku in unit.skus] == [
        "BD046A",
        "BD046A+AXBD001A",
        "BD046B",
        "BD046B+AXBD001A",
        "BD046C",
        "BD046C+AXBD001A",
    ]
    # 主图仍只取当前编码目录
    assert [p.name for p in unit.carousel_images] == ["1.png", "2.png", "3.png", "4.png", "5.png"]
    assert unit.root.name == "BD046A"


def test_multi_image_sets_are_independent_listing_units(tmp_path: Path):
    """第一套图 / 第二套图 为独立上架目标，SKU 不跨套图合并。"""
    root = tmp_path / "assets"
    for image_set, styles in [
        ("第一套图", ["BD021A卡皮巴拉笔袋"]),
        ("第二套图", ["BD021A卡皮巴拉笔袋", "BD021B米色笔袋"]),
    ]:
        for style in styles:
            code_dir = root / "BD021" / image_set / style
            _touch_code_dir(
                code_dir,
                specs=[f"{style}.jpg", f"{style}+YKL001A.jpg"],
            )

    settings = YamlSettings(paths=PathsConfig(assets_root=str(root)))
    units_set1 = resolve_listing_units(["BD021/第一套图/BD021A卡皮巴拉笔袋"], settings, assets_root=root)
    assert len(units_set1) == 1
    assert units_set1[0].image_set == "第一套图"
    assert all(sku.style_code == "BD021A卡皮巴拉笔袋" for sku in units_set1[0].skus)
    assert not any("BD021B" in sku.style_code for sku in units_set1[0].skus)

    units_set2 = resolve_listing_units(["BD021/第二套图/BD021A卡皮巴拉笔袋"], settings, assets_root=root)
    assert len(units_set2) == 1
    assert units_set2[0].image_set == "第二套图"
    # 第二套图内兄弟合并
    assert any(sku.style_code.startswith("BD021B") for sku in units_set2[0].skus)
    assert any(sku.style_code == "BD021A卡皮巴拉笔袋" for sku in units_set2[0].skus)


def test_listing_targets_include_all_image_sets_sorted(tmp_path: Path):
    root = tmp_path / "assets"
    for image_set in ["第二套图", "第一套图", "套图3"]:
        unit_root = root / "BD720" / image_set / "BD720A"
        unit_root.mkdir(parents=True)
        if image_set == "第一套图":
            for index in range(1, 6):
                (unit_root / f"{index}.png").write_bytes(b"img")

    targets = list_local_listing_targets(root)
    selectors = [item["selector"] for item in targets]
    assert selectors == ["BD720/第一套图", "BD720/第二套图", "BD720/套图3"]
    # 空套图也保留
    empty = next(item for item in targets if item["image_set"] == "第二套图")
    assert empty["product_codes"] == []
    assert empty["product_count"] == 0


def test_resolve_short_code_matches_chinese_suffix_folder(tmp_path: Path):
    root = tmp_path / "assets"
    code_dir = root / "BD021" / "第一套图" / "BD021A卡皮巴拉笔袋"
    _touch_code_dir(code_dir, specs=["BD021A卡皮巴拉笔袋.jpg"])

    settings = YamlSettings(paths=PathsConfig(assets_root=str(root)))
    units = resolve_listing_units(["BD021/第一套图/BD021A"], settings, assets_root=root)
    assert len(units) == 1
    assert units[0].product_code == "BD021A卡皮巴拉笔袋"
    assert len(units[0].skus) == 1


def test_build_listing_unit_detail_and_material(tmp_path: Path):
    product_dir = tmp_path / "BD046A"
    product_dir.mkdir()
    for name in ("1.png", "6.png", "7.png", "8.png", "9.png"):
        (product_dir / name).write_bytes(b"x")

    unit = build_listing_unit("BD046A", "", product_dir, family_code="BD046")
    assert [p.name for p in unit.detail_images] == ["6.png", "7.png", "8.png"]
    assert unit.material_image is not None
    assert unit.material_image.name == "9.png"

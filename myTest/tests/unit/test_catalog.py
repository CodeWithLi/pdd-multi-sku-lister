"""catalog Skill 单元测试（无需浏览器）。"""

from pdd_agent.core.config import MultiSpecConfig, PathsConfig, YamlSettings
from pdd_agent.skills.listing.catalog import (
    _parse_combo_code,
    is_image_set_dir,
    list_image_sets,
    list_listing_targets,
    parse_all_listings,
    parse_listing_target,
)
from pdd_agent.skills.listing.pdd_product_catalog import BUNDLE_MODEL_CODE, get_pdd_product_catalog


def test_image_set_pattern():
    assert is_image_set_dir("第一套")
    assert is_image_set_dir("第一套图")
    assert is_image_set_dir("第二套图")
    assert not is_image_set_dir("BD046A")
    assert not is_image_set_dir("主图")


def test_list_image_sets_empty(tmp_path):
    """商品目录不存在时返回空列表。"""
    assert list_image_sets("BD999", tmp_path) == []


def test_new_flat_image_layout(tmp_path, monkeypatch):
    """新结构：母文件夹/套图/编码，1-5 主图、7-9 详情，根目录图片为 SKU 预览图。"""
    monkeypatch.setattr("pdd_agent.core.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("pdd_agent.paths.PROJECT_ROOT", tmp_path)
    get_pdd_product_catalog.cache_clear()
    root = tmp_path / "data/assets/商品上架规格文件"
    unit_root = root / "BD046" / "第一套" / "BD046A"
    unit_root.mkdir(parents=True)
    for index in range(1, 10):
        (unit_root / f"{index}.png").write_bytes(b"img")
    (unit_root / "BD046A+AXBD001A.png").write_bytes(b"preview")
    (unit_root / "BD046A+AXBD888.png").write_bytes(b"preview")
    (unit_root / "BD046A.png").write_bytes(b"preview")

    settings = YamlSettings(
        paths=PathsConfig(assets_root="data/assets/商品上架规格文件"),
        multi_spec=MultiSpecConfig(excel="missing.xlsx"),
    )

    assert list_image_sets("BD046A", root) == ["第一套"]
    units = parse_all_listings("BD046A", settings, include_excel_missing_previews=True)
    assert len(units) == 1
    unit = units[0]
    assert [p.name for p in unit.carousel_images] == ["1.png", "2.png", "3.png", "4.png", "5.png"]
    assert [p.name for p in unit.detail_images] == ["7.png", "8.png", "9.png"]
    assert "6.png" not in [p.name for p in unit.carousel_images + unit.detail_images]
    assert [sku.combo_folder for sku in unit.skus] == ["BD046A", "BD046A+AXBD001A", "BD046A+AXBD888"]
    assert unit.family_code == "BD046"

    listing_units = parse_all_listings("BD046A", settings)
    assert [sku.combo_folder for sku in listing_units[0].skus] == []


def test_listing_target_selector_expands_family_and_image_set(tmp_path, monkeypatch):
    monkeypatch.setattr("pdd_agent.core.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("pdd_agent.paths.PROJECT_ROOT", tmp_path)
    get_pdd_product_catalog.cache_clear()
    root = tmp_path / "data/assets/商品上架规格文件"
    for code in ["BD046A", "BD046B", "BD046C"]:
        unit_root = root / "BD046" / "第一套" / code
        unit_root.mkdir(parents=True)
        for index in range(1, 10):
            (unit_root / f"{index}.png").write_bytes(b"img")
        (unit_root / f"{code}.png").write_bytes(b"preview")
        (unit_root / f"{code}+AXBD001A.png").write_bytes(b"preview")

    settings = YamlSettings(
        paths=PathsConfig(assets_root="data/assets/商品上架规格文件"),
        multi_spec=MultiSpecConfig(excel="missing.xlsx"),
    )

    targets = list_listing_targets(settings)
    assert [item.selector for item in targets] == ["BD046/第一套"]
    assert list(targets[0].product_codes) == ["BD046A", "BD046B", "BD046C"]

    units = parse_listing_target("BD046/第一套", settings, include_excel_missing_previews=True)
    assert [unit.product_code for unit in units] == ["BD046A", "BD046B", "BD046C"]
    assert all(unit.image_set == "第一套" for unit in units)

    single = parse_listing_target(
        "BD046/第一套/BD046A", settings, include_excel_missing_previews=True
    )
    assert len(single) == 1
    assert single[0].product_code == "BD046A"
    assert single[0].merchant_code == "BD046A"
    assert single[0].family_code == "BD046"
    assert [sku.combo_folder for sku in single[0].skus] == [
        "BD046A",
        "BD046A+AXBD001A",
        "BD046B",
        "BD046B+AXBD001A",
        "BD046C",
        "BD046C+AXBD001A",
    ]
    assert [p.name for p in single[0].carousel_images] == ["1.png", "2.png", "3.png", "4.png", "5.png"]


def test_parse_combo_code_two_part_is_normal_combo():
    assert _parse_combo_code("BD719A+GJ361A", "BD719A") == ("BD719A", "GJ361A")
    assert _parse_combo_code("BD719A", "BD719A") == ("BD719A", "BD719A")


def test_parse_combo_code_multi_part_is_bundle():
    assert _parse_combo_code("BD719A+YKL001A+YKL020A+GJ361A", "BD719A") == (
        "BD719A",
        BUNDLE_MODEL_CODE,
    )
    assert _parse_combo_code("BD719B+YKL001H+YKL020A+GJ318B", "BD719B") == (
        "BD719B",
        BUNDLE_MODEL_CODE,
    )


def test_bundle_preview_parsed_as_sku(tmp_path, monkeypatch):
    """多段 + 规格图按套装入库，combo_folder 保留完整文件名。"""
    monkeypatch.setattr("pdd_agent.core.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("pdd_agent.paths.PROJECT_ROOT", tmp_path)
    get_pdd_product_catalog.cache_clear()
    root = tmp_path / "data/assets/商品上架规格文件"
    unit_root = root / "BD719" / "第一套图" / "BD719A"
    unit_root.mkdir(parents=True)
    for index in range(1, 10):
        (unit_root / f"{index}.png").write_bytes(b"img")
    (unit_root / "BD719A.png").write_bytes(b"preview")
    (unit_root / "BD719A+GJ361A.png").write_bytes(b"preview")
    (unit_root / "BD719A+YKL001A+YKL020A+GJ361A.png").write_bytes(b"preview")

    settings = YamlSettings(
        paths=PathsConfig(assets_root="data/assets/商品上架规格文件"),
        multi_spec=MultiSpecConfig(excel="missing.xlsx"),
    )
    unit = parse_listing_target(
        "BD719/第一套图/BD719A", settings, include_excel_missing_previews=True
    )[0]
    assert [sku.combo_folder for sku in unit.skus] == [
        "BD719A",
        "BD719A+GJ361A",
        "BD719A+YKL001A+YKL020A+GJ361A",
    ]
    bundle = next(sku for sku in unit.skus if sku.model_code == BUNDLE_MODEL_CODE)
    assert bundle.style_code == "BD719A"
    assert bundle.preview_image.name == "BD719A+YKL001A+YKL020A+GJ361A.png"


def test_sibling_spec_merge_ignores_misnamed_preview_files(tmp_path, monkeypatch):
    """兄弟目录中误放的 BD046A.png 不应合并进 BD046A 上架单元。"""
    monkeypatch.setattr("pdd_agent.core.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("pdd_agent.paths.PROJECT_ROOT", tmp_path)
    get_pdd_product_catalog.cache_clear()
    root = tmp_path / "data/assets/商品上架规格文件"
    for code in ["BD046A", "BD046B", "BD046C"]:
        unit_root = root / "BD046" / "第一套" / code
        unit_root.mkdir(parents=True)
        for index in range(1, 10):
            (unit_root / f"{index}.png").write_bytes(b"img")
        (unit_root / f"{code}.png").write_bytes(b"preview")
        (unit_root / f"{code}+AXBD001A.png").write_bytes(b"preview")
    # 误放在 BD046B 目录下的 BD046A 规格图
    (root / "BD046" / "第一套" / "BD046B" / "BD046A.png").write_bytes(b"bad")

    settings = YamlSettings(
        paths=PathsConfig(assets_root="data/assets/商品上架规格文件"),
        multi_spec=MultiSpecConfig(excel="missing.xlsx"),
    )
    unit = parse_listing_target(
        "BD046/第一套/BD046A", settings, include_excel_missing_previews=True
    )[0]
    assert [sku.combo_folder for sku in unit.skus] == [
        "BD046A",
        "BD046A+AXBD001A",
        "BD046B",
        "BD046B+AXBD001A",
        "BD046C",
        "BD046C+AXBD001A",
    ]

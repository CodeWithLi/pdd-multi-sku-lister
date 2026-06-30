"""catalog Skill 单元测试（无需浏览器）。"""

from pathlib import Path

from pdd_agent.core.config import MultiSpecConfig, PathsConfig, YamlSettings
from pdd_agent.skills.listing.catalog import (
    _parse_combo_code,
    is_image_set_dir,
    list_image_sets,
    list_listing_targets,
    parse_all_listings,
    parse_listing_target,
)
from pdd_agent.skills.listing.platform_skip_siblings import filter_listing_unit_skus_by_platform_skip
from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.pdd_product_catalog import BUNDLE_MODEL_CODE, PddProductEntry, get_pdd_product_catalog


def test_image_set_pattern():
    assert is_image_set_dir("第一套")
    assert is_image_set_dir("第一套图")
    assert is_image_set_dir("第二套图")
    assert is_image_set_dir("2套")
    assert is_image_set_dir("2套图")
    assert is_image_set_dir("套图2")
    assert is_image_set_dir("第2套-改版")
    assert is_image_set_dir("第二套（备用）")
    assert not is_image_set_dir("BD046A")
    assert not is_image_set_dir("主图")


def test_list_image_sets_empty(tmp_path):
    """商品目录不存在时返回空列表。"""
    assert list_image_sets("BD999", tmp_path) == []


def test_new_flat_image_layout(tmp_path, monkeypatch):
    """新结构：母文件夹/套图/编码，1-5 主图、6-8 详情、9 商品素材，根目录图片为 SKU 预览图。"""
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
    assert [p.name for p in unit.detail_images] == ["6.png", "7.png", "8.png"]
    assert unit.material_image and unit.material_image.name == "9.png"
    assert "9.png" not in [p.name for p in unit.carousel_images + unit.detail_images]
    assert [sku.combo_folder for sku in unit.skus] == ["BD046A", "BD046A+AXBD001A", "BD046A+AXBD888"]
    assert unit.family_code == "BD046"

    monkeypatch.setattr(
        "pdd_agent.skills.listing.catalog._load_product_catalog",
        lambda settings=None: {},
    )
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


def test_listing_targets_include_all_image_sets(tmp_path, monkeypatch):
    monkeypatch.setattr("pdd_agent.core.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("pdd_agent.paths.PROJECT_ROOT", tmp_path)
    get_pdd_product_catalog.cache_clear()
    root = tmp_path / "data/assets/商品上架规格文件"
    for image_set in ["第一套", "第二套", "套图3"]:
        unit_root = root / "BD720" / image_set / "BD720A"
        unit_root.mkdir(parents=True)
        if image_set == "第一套":
            for index in range(1, 10):
                (unit_root / f"{index}.png").write_bytes(b"img")
            (unit_root / "BD720A.png").write_bytes(b"preview")
        # 第二套 / 套图3 故意留空目录，也应出现在 targets 中

    settings = YamlSettings(
        paths=PathsConfig(assets_root="data/assets/商品上架规格文件"),
        multi_spec=MultiSpecConfig(excel="missing.xlsx"),
    )

    targets = list_listing_targets(settings)
    assert [item.selector for item in targets] == [
        "BD720/第一套",
        "BD720/第二套",
        "BD720/套图3",
    ]
    by_set = {item.image_set: item for item in targets}
    assert list(by_set["第一套"].product_codes) == ["BD720A"]
    assert list(by_set["第二套"].product_codes) == []
    assert list(by_set["套图3"].product_codes) == []


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


def test_parse_combo_code_keeps_chinese_product_name():
    assert _parse_combo_code("BD037A奶油泡芙笔袋+YKL001A", "BD037A奶油泡芙笔袋") == (
        "BD037A奶油泡芙笔袋",
        "YKL001A",
    )
    assert _parse_combo_code("BD037A奶油泡芙笔袋", "BD037A奶油泡芙笔袋") == (
        "BD037A奶油泡芙笔袋",
        "BD037A奶油泡芙笔袋",
    )
    assert _parse_combo_code("BD037A奶油泡芙笔袋+YKL020A+YKL001A+YKL004L", "BD037A奶油泡芙笔袋") == (
        "BD037A奶油泡芙笔袋",
        BUNDLE_MODEL_CODE,
    )


def test_parse_combo_component_codes_for_bundle():
    from pdd_agent.skills.listing.catalog import _parse_combo_component_codes

    assert _parse_combo_component_codes("BD032D+YKL020A+YKL004L+YKL007P", "BD032D") == [
        "BD032D",
        "YKL020A",
        "YKL004L",
        "YKL007P",
    ]
    assert _parse_combo_component_codes("BD719A+GJ361A", "BD719A") == ["BD719A", "GJ361A"]
    assert _parse_combo_component_codes("BD037A奶油泡芙笔袋+YKL001A", "BD037A奶油泡芙笔袋") == [
        "BD037A奶油泡芙笔袋",
        "YKL001A",
    ]


def test_resolve_combo_pricing_bundle_sums_all_components():
    from pdd_agent.skills.listing.listing_price_float import reset_listing_price_float_registry
    from pdd_agent.skills.listing.pdd_product_catalog import resolve_combo_pricing

    reset_listing_price_float_registry(enabled=False, single_float_min=0.0, single_float_max=0.0)
    catalog = {
        "BD032D": PddProductEntry("BD032D", "棕色笔袋", "笔袋", 2855, 14.0),
        "YKL020A": PddProductEntry("YKL020A", "磁吸夹", "亚克力", 100, 4.09),
        "YKL004L": PddProductEntry("YKL004L", "套尺", "亚克力", 100, 5.09),
        "YKL007P": PddProductEntry("YKL007P", "挂件", "亚克力", 100, 3.96),
    }
    components = ["BD032D", "YKL020A", "YKL004L", "YKL007P"]
    inv, gp, sp = resolve_combo_pricing(
        "BD032D",
        BUNDLE_MODEL_CODE,
        catalog,
        {},
        bundle_components=components,
    )
    assert inv == "100"
    assert gp == "27.14"
    assert 27.14 <= float(sp) <= 29.14


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


def test_sibling_spec_merge_excludes_platform_skipped_codes(tmp_path, monkeypatch):
    """已平台跳过的兄弟款不再并入当前上架单元的规格表。"""
    monkeypatch.setattr("pdd_agent.core.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("pdd_agent.paths.PROJECT_ROOT", tmp_path)
    get_pdd_product_catalog.cache_clear()
    root = tmp_path / "data/assets/商品上架规格文件"
    for code in ["BD329A", "BD329B", "BD329C"]:
        unit_root = root / "BD329" / "第一套图" / code
        unit_root.mkdir(parents=True)
        for index in range(1, 10):
            (unit_root / f"{index}.png").write_bytes(b"img")
        (unit_root / f"{code}.png").write_bytes(b"preview")
        (unit_root / f"{code}+AXBD001A.png").write_bytes(b"preview")

    def _is_skip(code: str, **kwargs) -> bool:
        return str(code or "").strip().upper() in {"BD329A", "BD329B"}

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.platform_skip_dedupe_cache.is_platform_skip_merchant_code",
        _is_skip,
    )

    settings = YamlSettings(
        paths=PathsConfig(assets_root="data/assets/商品上架规格文件"),
        multi_spec=MultiSpecConfig(excel="missing.xlsx"),
    )

    unit_b = parse_listing_target(
        "BD329/第一套图/BD329B", settings, include_excel_missing_previews=True
    )[0]
    assert [sku.combo_folder for sku in unit_b.skus] == [
        "BD329B",
        "BD329B+AXBD001A",
        "BD329C",
        "BD329C+AXBD001A",
    ]

    unit_c = parse_listing_target(
        "BD329/第一套图/BD329C", settings, include_excel_missing_previews=True
    )[0]
    assert [sku.combo_folder for sku in unit_c.skus] == [
        "BD329C",
        "BD329C+AXBD001A",
    ]


def test_filter_listing_unit_skus_by_platform_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.platform_skip_dedupe_cache.is_platform_skip_merchant_code",
        lambda code, **kwargs: str(code).strip().upper() == "BD329A",
    )
    unit = ListingUnit(
        product_code="BD329B",
        family_code="BD329",
        image_set="第一套图",
        root=tmp_path,
        skus=[
            SkuCombo(
                style_code="BD329A",
                style_name="蓝",
                model_code="m1",
                model_name="笔袋",
                combo_folder="BD329A",
                preview_image=tmp_path / "a.png",
            ),
            SkuCombo(
                style_code="BD329B",
                style_name="粉",
                model_code="m1",
                model_name="笔袋",
                combo_folder="BD329B",
                preview_image=tmp_path / "b.png",
            ),
            SkuCombo(
                style_code="BD329C",
                style_name="绿",
                model_code="m1",
                model_name="笔袋",
                combo_folder="BD329C",
                preview_image=tmp_path / "c.png",
            ),
        ],
        style_codes=["BD329A", "BD329B", "BD329C"],
        model_codes=["笔袋"],
    )
    removed = filter_listing_unit_skus_by_platform_skip(unit)
    assert removed == ["BD329A"]
    assert [sku.style_code for sku in unit.skus] == ["BD329B", "BD329C"]
    assert unit.style_codes == ["BD329B", "BD329C"]


def test_minio_style_preview_filenames_with_chinese_suffix(tmp_path, monkeypatch):
    """MinIO：目录与规格图均带中文商品名，按 + 切段查飞书，不再截取字母编码。"""
    monkeypatch.setattr("pdd_agent.core.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("pdd_agent.paths.PROJECT_ROOT", tmp_path)
    get_pdd_product_catalog.cache_clear()
    root = tmp_path / "data/assets/商品上架规格文件"
    folder = "BD023A毛绒小狗笔袋"
    unit_root = root / "BD023" / "第一套图" / folder
    unit_root.mkdir(parents=True)
    for index in [1, 2, 3, 4, 5, 6, 7, 8, 9]:
        (unit_root / f"{index}.png").write_bytes(b"img")
    (unit_root / f"{folder}.png").write_bytes(b"preview")
    (unit_root / f"{folder}+YKL001N.png").write_bytes(b"preview")
    (unit_root / f"{folder}+YKL001L.png").write_bytes(b"preview")
    (unit_root / f"{folder}+YKL020A+YKL001N+YKL004L.png").write_bytes(b"preview")

    settings = YamlSettings(
        paths=PathsConfig(assets_root="data/assets/商品上架规格文件"),
        multi_spec=MultiSpecConfig(excel="missing.xlsx"),
    )
    units = parse_all_listings(folder, settings, include_excel_missing_previews=True)
    assert len(units) == 1
    unit = units[0]
    assert len(unit.carousel_images) == 5
    assert len(unit.detail_images) == 3
    assert unit.material_image and unit.material_image.name == "9.png"
    combo_folders = [sku.combo_folder for sku in unit.skus]
    assert len(unit.skus) == 4
    assert folder in combo_folders
    assert f"{folder}+YKL001N" in combo_folders
    assert f"{folder}+YKL001L" in combo_folders
    assert f"{folder}+YKL020A+YKL001N+YKL004L" in combo_folders
    style_models = {(sku.style_code, sku.model_code) for sku in unit.skus}
    assert (folder, folder) in style_models
    assert (folder, "YKL001N") in style_models
    assert (folder, "YKL001L") in style_models


def test_parse_combo_code_short_prefix_with_chinese_dir():
    folder = "BD037B奶油色长条笔袋"
    assert _parse_combo_code("BD037B+YKL001N", folder) == (folder, "YKL001N")
    assert _parse_combo_code("BD037B+YKL001N+YKL020D+YKU007P", folder) == (
        folder,
        BUNDLE_MODEL_CODE,
    )


def test_combo_slot_signature_consistent_across_colors():
    from pdd_agent.skills.listing.catalog import combo_slot_signature

    folder_a = "BD037A奶油泡芙笔袋"
    folder_b = "BD037B奶油色长条笔袋"
    assert combo_slot_signature(folder_a, folder_a) == "solo"
    assert combo_slot_signature("BD037B", folder_b) == "solo"
    assert combo_slot_signature(f"{folder_a}+YKL001N", folder_a) == combo_slot_signature(
        "BD037B+YKL001N", folder_b
    )
    assert combo_slot_signature(f"{folder_a}+YKL020A+YKL001N+YKL004L", folder_a).startswith(
        "bundle:"
    )
    assert combo_slot_signature("BD037B+YKL001N+YKL020D+YKU007P", folder_b).startswith(
        "bundle:"
    )


def test_preview_sort_key_bundle_after_single_combo():
    from pdd_agent.skills.listing.catalog import _preview_sort_key

    folder = "BD037B奶油色长条笔袋"
    paths = [
        Path("BD037B+YKL001N+YKL020D+YKU007P.png"),
        Path(f"{folder}+YKL020A+YKL001N+YKL004L.png"),
        Path(f"{folder}+YKL001N.png"),
        Path(f"{folder}.png"),
    ]
    sorted_stems = [p.stem for p in sorted(paths, key=lambda p: _preview_sort_key(p, folder))]
    assert sorted_stems[0] == folder
    assert sorted_stems[1] == f"{folder}+YKL001N"
    assert sorted_stems[2:] == [
        "BD037B+YKL001N+YKL020D+YKU007P",
        f"{folder}+YKL020A+YKL001N+YKL004L",
    ]


def test_preview_stem_matches_short_prefix_dir():
    from pdd_agent.skills.listing.catalog import (
        _filter_preview_images_for_code_dir,
        _preview_stem_matches_code_dir,
    )

    folder = "BD037B奶油色长条笔袋"
    assert _preview_stem_matches_code_dir("BD037B+YKL001N", folder)
    assert _preview_stem_matches_code_dir(f"{folder}+YKL001N", folder)
    assert not _preview_stem_matches_code_dir("BD037A+YKL001N", folder)

    code_dir = Path(folder)
    previews = [
        Path("BD037B+YKL001N.png"),
        Path(f"{folder}+YKL001N.png"),
        Path("BD037A+YKL001N.png"),
    ]
    matched = _filter_preview_images_for_code_dir(code_dir, previews)
    assert [p.name for p in matched] == ["BD037B+YKL001N.png", f"{folder}+YKL001N.png"]

"""多规格素材目录解析 Skill。

当前主用结构：

data/assets/商品上架规格文件/
  BD046/                 # 母文件夹（family_code）
    第一套/
      BD046A/            # 商品编码（文件夹名 = 上架货号）
        1.png ... 5.png  # 主图
        6.png            # 白底占位，不上传
        7.png ... 9.png  # 详情图
        BD046A+AXBD001A.png  # 规格图，文件名即组合编码

上架 BD046A 时：主图/详情图取自 BD046A 目录；规格图依次合并同套图下
所有兄弟编码目录（A-Z，最多 26 个）的规格图，写入该商品的 SKU 表。

代码仍保留旧结构兼容，避免历史数据/测试立即失效。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import StructuredTool

from pdd_agent.core.config import YamlSettings
from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.base import Skill
from pdd_agent.skills.listing.pdd_product_catalog import (
    PddProductEntry,
    default_catalog_path,
    get_pdd_product_catalog,
    load_pdd_product_catalog,
    lookup_catalog_spec,
    resolve_combo_pricing,
)
from pdd_agent.skills.listing.spec_labels import enrich_listing_unit_specs

RESERVED_DIRS = frozenset({"主图", "详情页"})
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PREVIEW_NAMES = ("预览图.png", "预览图.jpg", "预览图.jpeg", "预览图.webp")
IMAGE_SET_PATTERN = re.compile(r"^第.+套(图)?$")


@dataclass(frozen=True)
class ListingTargetOption:
    selector: str
    family_code: str
    image_set: str
    product_codes: tuple[str, ...]


def _natural_sort_key(path: Path):
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def _image_set_sort_key(name: str):
    cn_map = {
        "零": 0,
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    match = re.search(r"第([一二三四五六七八九十\d]+)套", name)
    if not match:
        return (1, name)
    token = match.group(1)
    if token.isdigit():
        return (0, int(token))
    if token in cn_map:
        return (0, cn_map[token])
    if token.startswith("十") and len(token) == 2 and token[1] in cn_map:
        return (0, 10 + cn_map[token[1]])
    return (0, sum(cn_map.get(ch, 0) for ch in token))


def is_image_set_dir(name: str) -> bool:
    return bool(IMAGE_SET_PATTERN.match(name.strip()))


def _load_product_catalog(settings: YamlSettings | None = None) -> dict[str, PddProductEntry]:
    """上架唯一商品数据源：拼多多所有商品.xls（可在系统设置中改路径）。"""
    if settings is not None:
        path = settings.multi_spec.excel_path
        if path.is_file():
            catalog = load_pdd_product_catalog(path)
            if catalog:
                return catalog
        default_path = default_catalog_path()
        if default_path.is_file() and default_path != path:
            return load_pdd_product_catalog(default_path)
        return {}
    return get_pdd_product_catalog()


def _collect_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
    return sorted(files, key=_natural_sort_key)


def _numbered_image_index(path: Path) -> int | None:
    if path.suffix.lower() not in IMAGE_EXTS:
        return None
    stem = path.stem.strip()
    return int(stem) if stem.isdigit() else None


def _collect_numbered_images(folder: Path, indexes: set[int]) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and (idx := _numbered_image_index(p)) is not None and idx in indexes
    ]
    return sorted(files, key=lambda p: _numbered_image_index(p) or 0)


def _collect_flat_preview_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and _numbered_image_index(p) is None
    ]
    return sorted(files, key=_natural_sort_key)


def _filter_preview_images_for_code_dir(code_dir: Path, previews: list[Path]) -> list[Path]:
    """
    兄弟目录合并规格图时，只保留与文件夹商品编码匹配的规格图。
    例如 BD046B/ 目录仅接受 BD046B.png、BD046B+AXBD001A.png，忽略误放的 BD046A.png。
    """
    code = code_dir.name.strip()
    if not code:
        return previews
    combo_prefix = f"{code}+"
    filtered: list[Path] = []
    for preview in previews:
        stem = preview.stem.strip()
        if stem == code or stem.startswith(combo_prefix):
            filtered.append(preview)
    return filtered


def _preview_sort_key(path: Path, product_code: str):
    parsed = _parse_combo_code(path.stem, product_code)
    if parsed and parsed[0] == product_code and parsed[1] == product_code:
        return (0, _natural_sort_key(path))
    return (1, _natural_sort_key(path))


def _find_preview_image(combo_dir: Path) -> Path | None:
    for name in PREVIEW_NAMES:
        p = combo_dir / name
        if p.is_file():
            return p
    imgs = _collect_images(combo_dir)
    return imgs[0] if imgs else None


def _parse_combo_code(name: str, default_style_code: str = "") -> tuple[str, str] | None:
    stem = Path(name).stem.strip()
    if not stem:
        return None
    if "+" in stem:
        left, right = stem.split("+", 1)
        left, right = left.strip(), right.strip()
        if left and right:
            return left, right
        return None
    if default_style_code:
        return default_style_code, stem
    return stem, stem


def _new_layout_units(product_code: str, assets_root: Path) -> list[tuple[str, Path]]:
    """返回新结构中某个实际商品编码的 [(套图名, 编码目录)]。"""
    if not assets_root.is_dir():
        return []
    units: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    for family_dir in sorted((p for p in assets_root.iterdir() if p.is_dir()), key=lambda p: p.name):
        for set_dir in sorted((p for p in family_dir.iterdir() if p.is_dir()), key=lambda p: _image_set_sort_key(p.name)):
            if not is_image_set_dir(set_dir.name):
                continue
            code_dir = set_dir / product_code
            if code_dir.is_dir() and code_dir not in seen:
                units.append((set_dir.name, code_dir))
                seen.add(code_dir)

    return units


def _new_layout_product_codes(assets_root: Path) -> list[str]:
    codes: set[str] = set()
    if not assets_root.is_dir():
        return []
    for family_dir in assets_root.iterdir():
        if not family_dir.is_dir():
            continue
        for set_dir in family_dir.iterdir():
            if not set_dir.is_dir() or not is_image_set_dir(set_dir.name):
                continue
            for code_dir in set_dir.iterdir():
                if code_dir.is_dir() and any(_numbered_image_index(p) is not None for p in code_dir.iterdir() if p.is_file()):
                    codes.add(code_dir.name)
    return sorted(codes)


def _code_dir_has_numbered_images(code_dir: Path) -> bool:
    return code_dir.is_dir() and any(
        _numbered_image_index(p) is not None for p in code_dir.iterdir() if p.is_file()
    )


def _new_layout_listing_targets(assets_root: Path) -> list[ListingTargetOption]:
    targets: list[ListingTargetOption] = []
    if not assets_root.is_dir():
        return targets
    for family_dir in sorted((p for p in assets_root.iterdir() if p.is_dir()), key=lambda p: p.name):
        for set_dir in sorted(
            (p for p in family_dir.iterdir() if p.is_dir() and is_image_set_dir(p.name)),
            key=lambda p: _image_set_sort_key(p.name),
        ):
            codes = tuple(
                sorted(
                    [
                        code_dir.name
                        for code_dir in set_dir.iterdir()
                        if _code_dir_has_numbered_images(code_dir)
                    ]
                )
            )
            if not codes:
                continue
            targets.append(
                ListingTargetOption(
                    selector=f"{family_dir.name}/{set_dir.name}",
                    family_code=family_dir.name,
                    image_set=set_dir.name,
                    product_codes=codes,
                )
            )
    return targets


def _parse_listing_target_selector(selector: str) -> tuple[str, str] | None:
    """解析「母编码/套图」两级 selector，如 BD046/第一套。"""
    raw = str(selector or "").strip()
    if "/" not in raw:
        return None
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if len(parts) != 2:
        return None
    family_code, image_set = parts
    if not family_code or not image_set or not is_image_set_dir(image_set):
        return None
    return family_code, image_set


def _parse_listing_target_product_selector(selector: str) -> tuple[str, str, str] | None:
    """解析「母编码/套图/商品编码」三级 selector，如 BD046/第一套/BD046A。"""
    raw = str(selector or "").strip()
    if "/" not in raw:
        return None
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if len(parts) != 3:
        return None
    family_code, image_set, product_code = parts
    if not family_code or not image_set or not product_code or not is_image_set_dir(image_set):
        return None
    return family_code, image_set, product_code


def _list_sibling_code_dirs(set_dir: Path) -> list[Path]:
    """同套图目录下所有商品编码文件夹，按名称 A-Z 排序，最多 26 个。"""
    if not set_dir.is_dir():
        return []
    dirs = [
        path
        for path in set_dir.iterdir()
        if path.is_dir() and _code_dir_has_numbered_images(path)
    ]
    return sorted(dirs, key=lambda p: p.name.upper())[:26]


def _append_skus_from_previews(
    unit: ListingUnit,
    previews: list[Path],
    default_style_code: str,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
    *,
    include_excel_missing_previews: bool,
    seen_combo_keys: set[tuple[str, str]],
    source_label: str = "",
) -> None:
    """将规格图解析为 SKU 并追加到 unit（按款式+型号去重）。"""
    label = unit.listing_label
    prefix = f"[{label}]"
    if source_label:
        prefix = f"[{label}][{source_label}]"

    for preview in previews:
        parsed = _parse_combo_code(preview.stem, default_style_code)
        if not parsed:
            unit.warnings.append(f"{prefix} 规格图文件名无法解析组合编码: {preview.name}")
            continue

        style_code, model_code = parsed
        combo_key = (style_code, model_code)
        if combo_key in seen_combo_keys:
            continue
        seen_combo_keys.add(combo_key)

        style_key = style_code.strip().upper()
        model_key = model_code.strip().upper()
        is_combo = model_key != style_key
        style_entry = catalog.get(style_key)
        model_entry = catalog.get(model_key) if is_combo else style_entry

        if not catalog:
            if not include_excel_missing_previews:
                unit.warnings.append(f"{prefix} 商品表无编码[{style_code}]，不上架 {preview.name}")
                continue
        elif not style_entry:
            if not include_excel_missing_previews:
                unit.warnings.append(f"{prefix} 商品表无款式编码[{style_code}]，不上架 {preview.name}")
                continue
            unit.warnings.append(f"{prefix} 商品表无款式编码[{style_code}]，仅后台展示不上架 {preview.name}")
        elif is_combo and not model_entry:
            if not include_excel_missing_previews:
                unit.warnings.append(f"{prefix} 商品表无子编码[{model_code}]，不上架 {preview.name}")
                continue
            unit.warnings.append(f"{prefix} 商品表无子编码[{model_code}]，仅后台展示不上架 {preview.name}")

        style_name = lookup_catalog_spec(style_code, catalog) or style_code
        model_name = lookup_catalog_spec(model_code, catalog) or model_code
        if catalog and style_entry:
            style_name = style_code
            model_name = model_code if is_combo else style_code

        if style_code not in unit.style_codes:
            unit.style_codes.append(style_code)
        if model_code not in unit.model_codes:
            unit.model_codes.append(model_code)

        inv, gp, sp = resolve_combo_pricing(style_code, model_code, catalog, defaults)
        unit.skus.append(
            SkuCombo(
                style_code=style_code,
                style_name=style_name,
                model_code=model_code,
                model_name=model_name,
                combo_folder=preview.stem,
                preview_image=preview,
                inventory=inv,
                group_price=gp,
                single_price=sp,
            )
        )


def list_image_sets(product_code: str, assets_root: Path) -> list[str]:
    new_units = _new_layout_units(product_code, assets_root)
    if new_units:
        return sorted({name for name, _ in new_units}, key=_image_set_sort_key)

    root = assets_root / product_code
    if not root.is_dir():
        return []
    return [
        d.name
        for d in sorted(root.iterdir(), key=lambda p: _image_set_sort_key(p.name))
        if d.is_dir() and is_image_set_dir(d.name)
    ]


def parse_new_listing_unit(
    product_code: str,
    unit_root: Path,
    image_set: str,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
    *,
    include_excel_missing_previews: bool = False,
) -> ListingUnit:
    label = f"{product_code}/{image_set}" if image_set else product_code
    family_code = ""
    try:
        if unit_root.parent.name == image_set and unit_root.parent.parent:
            family_code = unit_root.parent.parent.name
    except Exception:
        family_code = ""
    unit = ListingUnit(
        product_code=product_code,
        family_code=family_code,
        image_set=image_set,
        root=unit_root,
    )
    unit.carousel_images = _collect_numbered_images(unit_root, {1, 2, 3, 4, 5})
    unit.detail_images = _collect_numbered_images(unit_root, {7, 8, 9})

    if not unit.carousel_images:
        unit.warnings.append(f"[{label}] 未找到 1-5 主图")
    if not unit.detail_images:
        unit.warnings.append(f"[{label}] 未找到 7-9 详情图")

    # 规格图：同套图下所有兄弟商品编码文件夹（A-Z），依次合并到当前上架单元。
    set_dir = unit_root.parent if unit_root.parent.name == image_set else unit_root
    sibling_dirs = _list_sibling_code_dirs(set_dir) if set_dir.is_dir() else [unit_root]
    if not sibling_dirs:
        sibling_dirs = [unit_root]

    seen_combo_keys: set[tuple[str, str]] = set()
    for sibling_dir in sibling_dirs:
        previews = _filter_preview_images_for_code_dir(
            sibling_dir,
            sorted(
                _collect_flat_preview_images(sibling_dir),
                key=lambda p: _preview_sort_key(p, sibling_dir.name),
            ),
        )
        _append_skus_from_previews(
            unit,
            previews,
            sibling_dir.name,
            catalog,
            defaults,
            include_excel_missing_previews=include_excel_missing_previews,
            seen_combo_keys=seen_combo_keys,
            source_label=sibling_dir.name,
        )

    if not unit.skus:
        unit.warnings.append(f"[{label}] 未解析到任何有效 SKU")
    else:
        enrich_listing_unit_specs(unit)
    return unit


def parse_legacy_listing_unit(
    product_code: str,
    unit_root: Path,
    image_set: str,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
) -> ListingUnit:
    label = f"{product_code}/{image_set}" if image_set else product_code
    unit = ListingUnit(product_code=product_code, image_set=image_set, root=unit_root)
    unit.carousel_images = _collect_images(unit_root / "主图")
    unit.detail_images = _collect_images(unit_root / "详情页")

    style_dirs = sorted(
        (p for p in unit_root.iterdir() if p.is_dir() and p.name not in RESERVED_DIRS),
        key=lambda p: p.name,
    )

    for style_dir in style_dirs:
        if is_image_set_dir(style_dir.name):
            continue

        style_code = style_dir.name
        style_name = lookup_catalog_spec(style_code, catalog)
        if style_name is None:
            unit.warnings.append(f"[{label}] 商品表无款式编码[{style_code}]，跳过")
            continue

        unit.style_codes.append(style_code)

        combo_dirs = sorted(
            (p for p in style_dir.iterdir() if p.is_dir()),
            key=lambda p: p.name,
        )
        for combo_dir in combo_dirs:
            parsed = _parse_combo_code(combo_dir.name, style_code)
            if not parsed:
                unit.warnings.append(f"[{label}] 组合文件夹格式错误: {combo_dir.name}")
                continue

            _, model_code = parsed
            model_name = lookup_catalog_spec(model_code, catalog)
            if model_name is None:
                unit.warnings.append(f"[{label}] 商品表无型号编码[{model_code}]，跳过")
                continue

            preview = _find_preview_image(combo_dir)
            if not preview:
                unit.warnings.append(f"[{label}] 缺少预览图: {style_code}/{combo_dir.name}")
                continue

            if model_code not in unit.model_codes:
                unit.model_codes.append(model_code)

            inv, gp, sp = resolve_combo_pricing(style_code, model_code, catalog, defaults)
            unit.skus.append(
                SkuCombo(
                    style_code=style_code,
                    style_name=style_name,
                    model_code=model_code,
                    model_name=model_name,
                    combo_folder=combo_dir.name,
                    preview_image=preview,
                    inventory=inv,
                    group_price=gp,
                    single_price=sp,
                )
            )

    if not unit.skus:
        unit.warnings.append(f"[{label}] 未解析到任何有效 SKU")
    return unit


def parse_listing_unit(
    product_code: str,
    unit_root: Path,
    image_set: str,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
    *,
    include_excel_missing_previews: bool = False,
) -> ListingUnit:
    if any(_numbered_image_index(p) is not None for p in unit_root.iterdir() if p.is_file()):
        return parse_new_listing_unit(
            product_code,
            unit_root,
            image_set,
            catalog,
            defaults,
            include_excel_missing_previews=include_excel_missing_previews,
        )
    return parse_legacy_listing_unit(product_code, unit_root, image_set, catalog, defaults)


def parse_all_listings(
    product_code: str,
    settings: YamlSettings,
    *,
    include_excel_missing_previews: bool = False,
) -> list[ListingUnit]:
    assets_root = settings.paths.resolve("assets_root")
    catalog = _load_product_catalog(settings)
    defaults = settings.multi_spec.defaults

    new_units = _new_layout_units(product_code, assets_root)
    if new_units:
        return [
            parse_new_listing_unit(
                product_code,
                unit_root,
                image_set,
                catalog,
                defaults,
                include_excel_missing_previews=include_excel_missing_previews,
            )
            for image_set, unit_root in new_units
        ]

    product_root = assets_root / product_code
    if not product_root.is_dir():
        return []

    image_sets = list_image_sets(product_code, assets_root)
    if image_sets:
        return [
            parse_listing_unit(
                product_code,
                product_root / image_set,
                image_set,
                catalog,
                defaults,
                include_excel_missing_previews=include_excel_missing_previews,
            )
            for image_set in image_sets
        ]
    return [
        parse_listing_unit(
            product_code,
            product_root,
            "",
            catalog,
            defaults,
            include_excel_missing_previews=include_excel_missing_previews,
        )
    ]


def parse_listing_target(
    target: str,
    settings: YamlSettings,
    *,
    include_excel_missing_previews: bool = False,
) -> list[ListingUnit]:
    product_selector = _parse_listing_target_product_selector(target)
    if product_selector:
        family_code, image_set, product_code = product_selector
        assets_root = settings.paths.resolve("assets_root")
        catalog = _load_product_catalog(settings)
        defaults = settings.multi_spec.defaults
        code_dir = assets_root / family_code / image_set / product_code
        if not code_dir.is_dir() or not _code_dir_has_numbered_images(code_dir):
            return []
        return [
            parse_new_listing_unit(
                product_code,
                code_dir,
                image_set,
                catalog,
                defaults,
                include_excel_missing_previews=include_excel_missing_previews,
            )
        ]

    selector = _parse_listing_target_selector(target)
    if not selector:
        return parse_all_listings(
            target,
            settings,
            include_excel_missing_previews=include_excel_missing_previews,
        )

    family_code, image_set = selector
    assets_root = settings.paths.resolve("assets_root")
    catalog = _load_product_catalog(settings)
    defaults = settings.multi_spec.defaults
    set_dir = assets_root / family_code / image_set
    if not set_dir.is_dir():
        return []

    units: list[ListingUnit] = []
    for code_dir in _list_sibling_code_dirs(set_dir):
        units.append(
            parse_new_listing_unit(
                code_dir.name,
                code_dir,
                image_set,
                catalog,
                defaults,
                include_excel_missing_previews=include_excel_missing_previews,
            )
        )
    return units


def list_listing_targets(settings: YamlSettings) -> list[ListingTargetOption]:
    assets_root = settings.paths.resolve("assets_root")
    return _new_layout_listing_targets(assets_root)


def list_product_codes(settings: YamlSettings) -> list[str]:
    assets_root = settings.paths.resolve("assets_root")
    new_codes = _new_layout_product_codes(assets_root)
    if new_codes:
        return new_codes
    if not assets_root.is_dir():
        return []
    return sorted(d.name for d in assets_root.iterdir() if d.is_dir() and not d.name.startswith("."))


class CatalogSkill(Skill):
    name = "parse_product_catalog"
    description = "解析多规格素材目录，返回可上架单元列表"

    def as_tool(self) -> StructuredTool:
        def _run(product_code: str) -> str:
            from pdd_agent.core.config import load_yaml_settings

            settings = load_yaml_settings()
            units = parse_all_listings(product_code, settings)
            lines = [f"{u.listing_label}: {len(u.skus)} skus" for u in units]
            return "\n".join(lines) if lines else "no units"

        return StructuredTool.from_function(
            name=self.name,
            description=self.description,
            func=_run,
        )

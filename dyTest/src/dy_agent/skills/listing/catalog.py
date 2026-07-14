"""素材目录解析 → ListingUnit（与拼多多结构对齐：单款/组合/套装 + 同套图兄弟合并 + 多套图）。"""

from __future__ import annotations

import re
from pathlib import Path

from dy_agent.core.config import YamlSettings, load_yaml_settings
from dy_agent.domain.models import ListingUnit, SkuCombo
from dy_agent.skills.listing.pdd_product_catalog import (
    BUNDLE_MODEL_CODE,
    PddProductEntry,
    load_pdd_product_catalog,
)
from dy_agent.skills.listing.platform_skip_siblings import filter_sibling_dirs_for_listing_specs

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_IMAGE_NUM_RE = re.compile(r"^(\d+)\.(png|jpg|jpeg|webp)$", re.I)
IMAGE_SET_PATTERN = re.compile(
    r"^(?:第?\s*[一二三四五六七八九十\d]+\s*套(?:图)?|套图\s*[一二三四五六七八九十\d]+)(?:[\s\-_（(].*)?$"
)


def is_image_set_dir(name: str) -> bool:
    return bool(IMAGE_SET_PATTERN.match(str(name or "").strip()))


def _image_set_sort_key(name: str) -> tuple:
    """套图排序：第一套/第二套/套图3 按套号数字序（对齐拼多多）。"""
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
    raw = str(name or "").strip()
    match = re.search(r"(?:第\s*)?([一二三四五六七八九十\d]+)\s*套", raw)
    if not match:
        match = re.search(r"套图\s*([一二三四五六七八九十\d]+)", raw)
    if not match:
        return (1, raw)
    token = match.group(1)
    if token.isdigit():
        return (0, int(token))
    if token in cn_map:
        return (0, cn_map[token])
    if token.startswith("十") and len(token) == 2 and token[1] in cn_map:
        return (0, 10 + cn_map[token[1]])
    return (0, sum(cn_map.get(ch, 0) for ch in token))


def parse_listing_target_selector(selector: str) -> tuple[str, str] | None:
    """Parse family/image_set selector, e.g. BD046/第一套."""
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


def parse_listing_target_product_selector(selector: str) -> tuple[str, str, str] | None:
    """Parse family/image_set/product_code selector."""
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


def _code_dir_has_numbered_images(code_dir: Path) -> bool:
    if not code_dir.is_dir():
        return False
    for path in code_dir.iterdir():
        if path.is_file() and _IMAGE_NUM_RE.match(path.name):
            return True
    return False


def _list_sibling_code_dirs(set_dir: Path) -> list[Path]:
    """同套图目录下所有商品编码文件夹，按名称 A-Z 排序，最多 26 个（对齐拼多多）。"""
    if not set_dir.is_dir():
        return []
    dirs = [
        path
        for path in set_dir.iterdir()
        if path.is_dir() and _code_dir_has_numbered_images(path)
    ]
    return sorted(dirs, key=lambda p: p.name.upper())[:26]


def list_local_listing_targets(assets_root: Path) -> list[dict]:
    """扫描素材根：每个 family/套图 一个 target（含空套图，套图按套号排序）。"""
    result: list[dict] = []
    if not assets_root.is_dir():
        return result
    for family_dir in sorted((p for p in assets_root.iterdir() if p.is_dir()), key=lambda p: p.name):
        set_dirs = sorted(
            (p for p in family_dir.iterdir() if p.is_dir() and is_image_set_dir(p.name)),
            key=lambda p: _image_set_sort_key(p.name),
        )
        for set_dir in set_dirs:
            codes = sorted(
                code_dir.name
                for code_dir in set_dir.iterdir()
                if _code_dir_has_numbered_images(code_dir)
            )
            result.append(
                {
                    "selector": f"{family_dir.name}/{set_dir.name}",
                    "family_code": family_dir.name,
                    "image_set": set_dir.name,
                    "product_codes": codes,
                    "product_count": len(codes),
                }
            )
    return result


def resolve_assets_root(settings: YamlSettings, assets_root: Path | None = None) -> Path:
    return assets_root or settings.paths.resolve("assets_root")


def _split_combo_stem_parts(stem: str, default_style_code: str = "") -> list[str]:
    """按 + 切段；首段若为文件夹短编码前缀则还原为完整主商品名（对齐拼多多）。"""
    text = Path(stem).stem.strip() if stem else ""
    if not text:
        return []
    if "+" not in text:
        return [text]
    parts = [part.strip() for part in text.split("+") if part.strip()]
    default_style = str(default_style_code or "").strip()
    if default_style and parts:
        first = parts[0]
        if first.casefold() != default_style.casefold():
            if default_style.casefold().startswith(first.casefold()) and len(first) < len(default_style):
                parts[0] = default_style
    return parts


def _parse_combo_component_codes(name: str, default_style_code: str = "") -> list[str]:
    stem = Path(name).stem.strip()
    if not stem:
        return []
    if "+" in stem:
        return list(dict.fromkeys(_split_combo_stem_parts(stem, default_style_code)))
    return [stem]


def load_product_catalog(settings: YamlSettings | None = None) -> dict[str, PddProductEntry]:
    """上架商品数据源：优先飞书快照，否则本地 Excel。"""
    from dy_agent.integrations.feishu.config import load_feishu_config
    from dy_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot
    from dy_agent.integrations.feishu.pdd_product_catalog_sync import load_unified_pdd_product_catalog

    snapshot = get_listing_feishu_snapshot()
    if snapshot is not None:
        cfg = load_feishu_config()
        catalog = snapshot.product_catalog(cfg)
        if catalog:
            return catalog

    catalog = load_unified_pdd_product_catalog(settings=settings)
    if catalog:
        return catalog

    settings = settings or load_yaml_settings()
    path = settings.multi_spec.excel_path
    if path.is_file():
        return load_pdd_product_catalog(path)
    return {}


def _code_dir_matches_product_code(dir_name: str, product_code: str) -> bool:
    """文件夹名与商品编码匹配（精确 / 短码前缀，如 BD021A ↔ BD021A卡皮巴拉笔袋）。"""
    left = str(dir_name or "").strip()
    right = str(product_code or "").strip()
    if not left or not right:
        return False
    if left.casefold() == right.casefold():
        return True
    if left.casefold().startswith(right.casefold()) and len(right) < len(left):
        return True
    if right.casefold().startswith(left.casefold()) and len(left) < len(right):
        return True
    return False


def _new_layout_units(product_code: str, assets_root: Path) -> list[tuple[str, str, Path]]:
    """全扫 family/套图，返回该编码在所有套图下的 [(family, image_set, code_dir)]。"""
    if not assets_root.is_dir():
        return []
    units: list[tuple[str, str, Path]] = []
    seen: set[Path] = set()
    for family_dir in sorted((p for p in assets_root.iterdir() if p.is_dir()), key=lambda p: p.name):
        for set_dir in sorted(
            (p for p in family_dir.iterdir() if p.is_dir() and is_image_set_dir(p.name)),
            key=lambda p: _image_set_sort_key(p.name),
        ):
            for code_dir in sorted((p for p in set_dir.iterdir() if p.is_dir()), key=lambda p: p.name):
                if not _code_dir_has_numbered_images(code_dir):
                    continue
                if not _code_dir_matches_product_code(code_dir.name, product_code):
                    continue
                resolved = code_dir.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                units.append((family_dir.name, set_dir.name, code_dir))
    return units


def discover_product_dirs(assets_root: Path, product_codes: list[str]) -> list[tuple[str, str, Path]]:
    """
    扫描素材根目录，返回 (product_code, image_set, dir_path)。
    支持多套图：{family}/{套名}/{product_code}/（短码可匹配中文后缀文件夹）。
    """
    results: list[tuple[str, str, Path]] = []
    if not assets_root.is_dir():
        return results

    for code in product_codes:
        for family_code, image_set, code_dir in _new_layout_units(code, assets_root):
            results.append((code_dir.name, image_set, code_dir))
            _ = family_code
    return results


def _collect_images(product_dir: Path) -> tuple[list[Path], list[Path], Path | None]:
    carousel: list[Path] = []
    detail: list[Path] = []
    material: Path | None = None

    for path in sorted(product_dir.iterdir()):
        if not path.is_file():
            continue
        m = _IMAGE_NUM_RE.match(path.name)
        if not m:
            continue
        num = int(m.group(1))
        if 1 <= num <= 5:
            carousel.append(path)
        elif num in (6, 7, 8):
            detail.append(path)
        elif num == 9:
            material = path

    carousel.sort(key=lambda p: int(_IMAGE_NUM_RE.match(p.name).group(1)))  # type: ignore[union-attr]
    detail.sort(key=lambda p: int(_IMAGE_NUM_RE.match(p.name).group(1)))  # type: ignore[union-attr]
    return carousel, detail, material


def _parse_combo_code(name: str, default_style_code: str = "") -> tuple[str, str] | None:
    """解析规格图文件名 → (款式编码, 子配件编码)。逻辑与拼多多 catalog 一致。"""
    stem = Path(name).stem.strip()
    if not stem:
        return None
    default_style = str(default_style_code or "").strip()
    if "+" in stem:
        parts = _split_combo_stem_parts(stem, default_style)
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0], parts[0]
        accessory_count = len(parts) - 1
        if accessory_count >= 2:
            return parts[0], BUNDLE_MODEL_CODE
        return parts[0], parts[1]
    if default_style:
        if stem.casefold() == default_style.casefold():
            return default_style, default_style
        if default_style.casefold().startswith(stem.casefold()) and len(stem) < len(default_style):
            return default_style, default_style
        return default_style, stem
    return stem, stem


def _preview_sort_key(path: Path, product_code: str) -> tuple:
    parsed = _parse_combo_code(path.stem, product_code)
    if not parsed:
        return (9, "", path.name.casefold())
    style, model = parsed
    if model.strip().upper() == style.strip().upper():
        tier = 0
        tie = ""
    elif model.strip().upper() == BUNDLE_MODEL_CODE:
        tier = 2
        tie = path.stem.casefold()
    else:
        tier = 1
        tie = model.strip().upper()
    return (tier, tie, path.name.casefold())


def _collect_flat_preview_images(folder: Path) -> list[Path]:
    """非编号图视为规格图（含单款 BD021A…jpg 与组合 BD021A…+YKL…jpg）。"""
    if not folder.is_dir():
        return []
    return [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS and not _IMAGE_NUM_RE.match(path.name)
    ]


def _preview_stem_matches_code_dir(stem: str, dir_name: str) -> bool:
    """规格图是否属于该编码文件夹（单款同名 / 组合首段匹配）。"""
    text = str(stem or "").strip()
    dir_key = str(dir_name or "").strip().casefold()
    if not text or not dir_key:
        return False
    if "+" in text:
        style_part = text.split("+", 1)[0].strip().casefold()
        if style_part == dir_key:
            return True
        return dir_key.startswith(style_part) and len(style_part) < len(dir_key)
    return text.casefold() == dir_key


def _filter_preview_images_for_code_dir(code_dir: Path, previews: list[Path]) -> list[Path]:
    dir_name = code_dir.name.strip()
    if not dir_name:
        return previews
    return [
        preview
        for preview in previews
        if preview.stem.strip() and _preview_stem_matches_code_dir(preview.stem, dir_name)
    ]


def _append_skus_from_previews(
    skus: list[SkuCombo],
    previews: list[Path],
    default_style_code: str,
    defaults: dict[str, str],
    *,
    seen_combo_keys: set[tuple[str, str]],
) -> None:
    """将规格图解析为 SKU 并追加（按款式+型号去重）。"""
    for path in previews:
        parsed = _parse_combo_code(path.stem, default_style_code)
        if not parsed:
            continue
        style_code, model_code = parsed
        combo_key = (style_code, model_code)
        if combo_key in seen_combo_keys:
            continue
        seen_combo_keys.add(combo_key)

        is_bundle = model_code.strip().upper() == BUNDLE_MODEL_CODE
        model_name = BUNDLE_MODEL_CODE if is_bundle else ""
        skus.append(
            SkuCombo(
                style_code=style_code,
                style_name="",
                model_code=model_code,
                model_name=model_name,
                combo_folder=path.stem,
                preview_image=path,
                inventory=defaults.get("inventory", "10"),
                price=defaults.get("price", defaults.get("group_price", "199.9")),
                market_price=defaults.get("market_price", defaults.get("single_price", "299.9")),
            )
        )


def _collect_skus_with_siblings(
    product_dir: Path,
    product_code: str,
    image_set: str,
    defaults: dict[str, str],
) -> list[SkuCombo]:
    """
    规格图：同套图下所有兄弟商品编码文件夹（A-Z）合并进当前上架单元（对齐拼多多）。
    主图/详情仍只取当前 product_dir。
    """
    if image_set and product_dir.parent.name == image_set:
        set_dir = product_dir.parent
    elif is_image_set_dir(product_dir.parent.name):
        set_dir = product_dir.parent
    else:
        set_dir = product_dir

    sibling_dirs = _list_sibling_code_dirs(set_dir) if set_dir.is_dir() else [product_dir]
    if not sibling_dirs:
        sibling_dirs = [product_dir]
    sibling_dirs = filter_sibling_dirs_for_listing_specs(
        sibling_dirs,
        listing_product_code=product_code,
    )
    if not sibling_dirs:
        sibling_dirs = [product_dir]

    skus: list[SkuCombo] = []
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
            skus,
            previews,
            sibling_dir.name,
            defaults,
            seen_combo_keys=seen_combo_keys,
        )
    return skus


def build_listing_unit(
    product_code: str,
    image_set: str,
    product_dir: Path,
    *,
    family_code: str = "",
    defaults: dict[str, str] | None = None,
) -> ListingUnit:
    """构建上架单元：主图取当前目录；SKU 合并同套图兄弟编码（对齐拼多多）。"""
    defaults = defaults or {}
    carousel, detail, material = _collect_images(product_dir)
    skus = _collect_skus_with_siblings(product_dir, product_code, image_set, defaults)
    warnings: list[str] = []
    if not carousel:
        warnings.append("缺少主图 (1-5.png)")
    if not skus:
        warnings.append("缺少 SKU 预览图 (款式+型号.png)")
    if not detail:
        warnings.append("缺少详情图 (6-8.png)")
    if material is None:
        warnings.append("缺少白底图 (9.png)")

    style_codes = list(dict.fromkeys(s.style_code for s in skus))
    model_codes = list(dict.fromkeys(s.model_code for s in skus))

    resolved_family = family_code
    if not resolved_family:
        try:
            if image_set and product_dir.parent.name == image_set:
                resolved_family = product_dir.parent.parent.name
            else:
                resolved_family = product_dir.parent.name
        except Exception:
            resolved_family = ""

    return ListingUnit(
        product_code=product_code,
        family_code=resolved_family,
        image_set=image_set,
        root=product_dir,
        carousel_images=carousel,
        detail_images=detail,
        material_image=material,
        style_codes=style_codes,
        model_codes=model_codes,
        skus=skus,
        warnings=warnings,
    )


def resolve_listing_units(
    product_codes: list[str],
    settings: YamlSettings,
    *,
    assets_root: Path | None = None,
) -> list[ListingUnit]:
    root = resolve_assets_root(settings, assets_root)
    defaults = settings.multi_spec.defaults
    units: list[ListingUnit] = []
    seen_labels: set[str] = set()

    for target in product_codes:
        raw = str(target or "").strip()
        if not raw:
            continue

        product_selector = parse_listing_target_product_selector(raw)
        if product_selector:
            family_code, image_set, product_code = product_selector
            set_dir = root / family_code / image_set
            product_dir = set_dir / product_code
            if not product_dir.is_dir() and set_dir.is_dir():
                # 短码匹配中文后缀文件夹
                for candidate in set_dir.iterdir():
                    if candidate.is_dir() and _code_dir_matches_product_code(candidate.name, product_code):
                        product_dir = candidate
                        product_code = candidate.name
                        break
            if product_dir.is_dir():
                unit = build_listing_unit(
                    product_code,
                    image_set,
                    product_dir,
                    family_code=family_code,
                    defaults=defaults,
                )
                if unit.listing_label not in seen_labels:
                    seen_labels.add(unit.listing_label)
                    units.append(unit)
            continue

        selector = parse_listing_target_selector(raw)
        if selector:
            family_code, image_set = selector
            set_dir = root / family_code / image_set
            if set_dir.is_dir():
                for product_dir in _list_sibling_code_dirs(set_dir):
                    unit = build_listing_unit(
                        product_dir.name,
                        image_set,
                        product_dir,
                        family_code=family_code,
                        defaults=defaults,
                    )
                    if unit.listing_label not in seen_labels:
                        seen_labels.add(unit.listing_label)
                        units.append(unit)
            continue

        for product_code, image_set, product_dir in discover_product_dirs(root, [raw]):
            family_code = (
                product_dir.parent.parent.name
                if image_set and product_dir.parent.name == image_set
                else product_dir.parent.name
            )
            unit = build_listing_unit(
                product_code,
                image_set,
                product_dir,
                family_code=family_code,
                defaults=defaults,
            )
            if unit.listing_label not in seen_labels:
                seen_labels.add(unit.listing_label)
                units.append(unit)

    return units

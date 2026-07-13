"""素材目录解析 → ListingUnit（基础版，与拼多多结构兼容）。"""

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

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_IMAGE_NUM_RE = re.compile(r"^(\d+)\.(png|jpg|jpeg|webp)$", re.I)
_COMBO_RE = re.compile(r"^(.+)\+(.+)\.(png|jpg|jpeg|webp)$", re.I)
IMAGE_SET_PATTERN = re.compile(
    r"^(?:第?\s*[一二三四五六七八九十\d]+\s*套(?:图)?|套图\s*[一二三四五六七八九十\d]+)(?:[\s\-_（(].*)?$"
)


def is_image_set_dir(name: str) -> bool:
    return bool(IMAGE_SET_PATTERN.match(str(name or "").strip()))


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


def list_local_listing_targets(assets_root: Path) -> list[dict]:
    """Scan local assets root and return listing target options."""
    result: list[dict] = []
    if not assets_root.is_dir():
        return result
    for family_dir in sorted((p for p in assets_root.iterdir() if p.is_dir()), key=lambda p: p.name):
        for set_dir in sorted(
            (p for p in family_dir.iterdir() if p.is_dir() and is_image_set_dir(p.name)),
            key=lambda p: p.name,
        ):
            codes = sorted(
                code_dir.name
                for code_dir in set_dir.iterdir()
                if _code_dir_has_numbered_images(code_dir)
            )
            if not codes:
                continue
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


def discover_product_dirs(assets_root: Path, product_codes: list[str]) -> list[tuple[str, str, Path]]:
    """
    扫描素材根目录，返回 (product_code, image_set, dir_path)。
    支持：
      - 旧版：{family}/{product_code}/
      - 多套：{family}/{套名}/{product_code}/
    """
    results: list[tuple[str, str, Path]] = []
    if not assets_root.is_dir():
        return results

    codes_upper = {c.upper() for c in product_codes}
    for family_dir in sorted(assets_root.iterdir()):
        if not family_dir.is_dir():
            continue
        # 直接子目录是 product_code
        for child in sorted(family_dir.iterdir()):
            if not child.is_dir():
                continue
            name = child.name.upper()
            if name in codes_upper:
                results.append((child.name, "", child))
                continue
            # 套图目录
            for product_dir in sorted(child.iterdir()):
                if product_dir.is_dir() and product_dir.name.upper() in codes_upper:
                    results.append((product_dir.name, child.name, product_dir))
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


def _collect_skus(product_dir: Path, defaults: dict[str, str]) -> list[SkuCombo]:
    """从商品目录规格图解析 SKU（款式 + 子配件），展示名由 enrich_listing_unit_specs 填充。"""
    default_style_code = product_dir.name
    skus: list[SkuCombo] = []
    seen: set[tuple[str, str]] = set()
    previews = [
        path
        for path in product_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS and _COMBO_RE.match(path.name)
    ]
    previews.sort(key=lambda p: _preview_sort_key(p, default_style_code))

    for path in previews:
        parsed = _parse_combo_code(path.stem, default_style_code)
        if not parsed:
            continue
        style_code, model_code = parsed
        combo_key = (style_code, model_code)
        if combo_key in seen:
            continue
        seen.add(combo_key)

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
    return skus


def build_listing_unit(
    product_code: str,
    image_set: str,
    product_dir: Path,
    *,
    family_code: str = "",
    defaults: dict[str, str] | None = None,
) -> ListingUnit:
    defaults = defaults or {}
    carousel, detail, material = _collect_images(product_dir)
    skus = _collect_skus(product_dir, defaults)
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

    return ListingUnit(
        product_code=product_code,
        family_code=family_code or product_dir.parent.parent.name,
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
            product_dir = root / family_code / image_set / product_code
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
                for product_dir in sorted((p for p in set_dir.iterdir() if p.is_dir()), key=lambda p: p.name):
                    if not _code_dir_has_numbered_images(product_dir):
                        continue
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
            unit = build_listing_unit(
                product_code,
                image_set,
                product_dir,
                family_code=product_dir.parent.parent.name if image_set else product_dir.parent.name,
                defaults=defaults,
            )
            if unit.listing_label not in seen_labels:
                seen_labels.add(unit.listing_label)
                units.append(unit)

    return units

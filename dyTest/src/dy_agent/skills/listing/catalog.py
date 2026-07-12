"""素材目录解析 → ListingUnit（基础版，与拼多多结构兼容）。"""

from __future__ import annotations

import re
from pathlib import Path

from dy_agent.core.config import YamlSettings
from dy_agent.domain.models import ListingUnit, SkuCombo

_IMAGE_NUM_RE = re.compile(r"^(\d+)\.(png|jpg|jpeg|webp)$", re.I)
_COMBO_RE = re.compile(r"^(.+)\+(.+)\.(png|jpg|jpeg|webp)$", re.I)


def resolve_assets_root(settings: YamlSettings, assets_root: Path | None = None) -> Path:
    return assets_root or settings.paths.resolve("assets_root")


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
        if m:
            num = int(m.group(1))
            if num == 6:
                continue
            if 1 <= num <= 5:
                carousel.append(path)
            elif num >= 7:
                detail.append(path)
            if num == 9:
                material = path
    carousel.sort(key=lambda p: int(_IMAGE_NUM_RE.match(p.name).group(1)))  # type: ignore[union-attr]
    detail.sort(key=lambda p: int(_IMAGE_NUM_RE.match(p.name).group(1)))  # type: ignore[union-attr]
    return carousel, detail, material


def _collect_skus(product_dir: Path, defaults: dict[str, str]) -> list[SkuCombo]:
    skus: list[SkuCombo] = []
    for path in sorted(product_dir.iterdir()):
        if not path.is_file():
            continue
        m = _COMBO_RE.match(path.name)
        if not m:
            continue
        style_code, model_code = m.group(1), m.group(2)
        skus.append(
            SkuCombo(
                style_code=style_code,
                style_name=style_code,
                model_code=model_code,
                model_name=model_code,
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
    for product_code, image_set, product_dir in discover_product_dirs(root, product_codes):
        family = product_dir.parent.parent.name if image_set else product_dir.parent.name
        units.append(
            build_listing_unit(
                product_code,
                image_set,
                product_dir,
                family_code=family,
                defaults=defaults,
            )
        )
    return units

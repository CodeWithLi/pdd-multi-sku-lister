"""款式（AI 颜色）+ 尺寸（商品表分组）规格名解析。"""

from __future__ import annotations

from pathlib import Path

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.llm.vision import detect_product_color, detect_sub_product_category, _fallback_color_from_catalog
from pdd_agent.db.repositories import get_cached_style_color, upsert_cached_style_color
from pdd_agent.skills.listing.pdd_product_catalog import (
    get_catalog_entry,
    get_pdd_product_catalog,
    infer_sub_product_category_rules,
    is_weak_sub_category,
    resolve_size_label,
)


def uses_pdd_spec_catalog(style_code: str) -> bool:
    catalog = get_pdd_product_catalog()
    return bool(catalog) and style_code.strip().upper() in catalog


def catalog_style_label(entry) -> str:
    """从商品表颜色规格提取可区分的款式名（AI 重复时兜底）。"""
    color = _fallback_color_from_catalog(entry)
    if color:
        return color
    spec = entry.color_spec.strip()
    return spec[:6] if spec else entry.code


def reconcile_style_color_with_catalog(ai_color: str, entry) -> tuple[str, str]:
    """用商品表颜色规格纠偏 AI 识色（尤其浅灰/黑色被误判为白色）。"""
    if not entry:
        return (ai_color or "").strip(), "ai"
    catalog_color = catalog_style_label(entry)
    ai_norm = (ai_color or "").strip()
    if not catalog_color:
        return ai_norm or entry.code, "ai"
    if not ai_norm:
        return catalog_color, "catalog"
    if ai_norm in ("白色", "米白色") and catalog_color not in ("白色", "米白色"):
        if _fallback_color_from_catalog(entry):
            return catalog_color, "ai+catalog"
    return ai_norm, "ai"


def persist_style_color_cache(
    unit: ListingUnit,
    colors: dict[str, str],
    *,
    source: str = "final",
) -> None:
    for style_code, color in colors.items():
        image = pick_style_reference_image(unit, style_code)
        image_str = str(image.resolve()) if image else None
        upsert_cached_style_color(
            style_code,
            color,
            source=source,
            image_path=image_str,
        )


def disambiguate_style_colors(
    colors: dict[str, str],
    catalog: dict,
) -> dict[str, str]:
    """保证同链接内每个款式编码对应唯一展示名（避免「白色」合并多个兄弟款）。"""
    result = dict(colors)
    by_name: dict[str, list[str]] = {}
    for code, name in colors.items():
        key = (name or code).strip() or code
        by_name.setdefault(key, []).append(code)

    for name, codes in by_name.items():
        if len(codes) <= 1:
            continue
        for code in codes:
            entry = catalog.get(code.strip().upper())
            if entry:
                result[code] = catalog_style_label(entry)

    used: set[str] = set()
    final: dict[str, str] = {}
    for code in colors:
        name = (result.get(code) or code).strip() or code
        if name in used:
            candidates = [f"{name}-{code[-1]}", code]
            for cand in candidates:
                if cand not in used:
                    name = cand
                    break
        final[code] = name
        used.add(name)
    return final


def ordered_style_names(unit: ListingUnit) -> list[str]:
    """按 style_codes 顺序输出款式名，每个兄弟款一条（不去重合并同名）。"""
    names: list[str] = []
    for code in unit.style_codes:
        for sku in unit.skus:
            if sku.style_code == code:
                names.append(sku.style_name)
                break
    return names


_STYLE_SOLO_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _find_sibling_code_dir(unit: ListingUnit, style_code: str) -> Path | None:
    """同套图下某款式编码文件夹（如 .../第一套图/BD716B）。"""
    set_dir = unit.root.parent
    if not set_dir.is_dir():
        return None
    target = style_code.strip().upper()
    for path in set_dir.iterdir():
        if path.is_dir() and path.name.upper() == target:
            return path
    return None


def _find_style_solo_image(code_dir: Path, style_code: str) -> Path | None:
    """文件夹内与编码同名的单款规格图（BD716A.png），不含组合图。"""
    target_stem = style_code.strip().upper()
    for path in sorted(code_dir.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _STYLE_SOLO_EXTS:
            continue
        if path.stem.strip().upper() == target_stem:
            return path
    return None


def pick_style_reference_image(unit: ListingUnit, style_code: str) -> Path | None:
    """款式识色专用：仅用 {款式编码}.png，不用组合规格图或主图。"""
    style_norm = style_code.strip().upper()

    for sku in unit.skus:
        if sku.style_code.strip().upper() != style_norm:
            continue
        if sku.combo_folder.strip().upper() != style_norm:
            continue
        if sku.preview_image.is_file():
            return sku.preview_image

    code_dir = _find_sibling_code_dir(unit, style_code)
    if code_dir:
        return _find_style_solo_image(code_dir, style_code)

    return None


def pick_sub_preview_image(unit: ListingUnit, model_code: str) -> Path | None:
    """组合 SKU 的规格预览图，供尺寸子类 AI 识别。"""
    model_norm = model_code.strip().upper()
    for sku in unit.skus:
        if sku.model_code.strip().upper() != model_norm:
            continue
        if sku.preview_image.is_file():
            return sku.preview_image
    return None


def build_sub_category_cache(unit: ListingUnit, account_id: str = "") -> dict[str, str]:
    """为单元内所有子配件编码解析尺寸子类（规则优先，弱匹配走 AI）。"""
    catalog = get_pdd_product_catalog()
    cache: dict[str, str] = {}
    prefix = f"[{account_id}] " if account_id else ""

    for sku in unit.skus:
        model_norm = sku.model_code.strip().upper()
        style_norm = sku.style_code.strip().upper()
        if not model_norm or model_norm == style_norm or model_norm in cache:
            continue

        entry = catalog.get(model_norm)
        if not entry:
            continue

        ruled = infer_sub_product_category_rules(entry)
        if ruled and not is_weak_sub_category(ruled):
            cache[model_norm] = ruled
            continue

        image = pick_sub_preview_image(unit, model_norm)
        print(
            f"{prefix}[{unit.listing_label}] AI识别尺寸子类：{model_norm} ← "
            f"{entry.color_spec}"
            f"{' / ' + image.name if image else ''}",
            flush=True,
        )
        cache[model_norm] = detect_sub_product_category(entry, image_path=image)

    return cache


def resolve_style_colors(unit: ListingUnit, account_id: str = "") -> dict[str, str]:
    catalog = get_pdd_product_catalog()
    colors: dict[str, str] = {}
    prefix = f"[{account_id}] " if account_id else ""
    for style_code in unit.style_codes:
        entry = catalog.get(style_code.strip().upper())
        image = pick_style_reference_image(unit, style_code)
        image_str = str(image.resolve()) if image else None
        cached = get_cached_style_color(style_code, image_str)
        if cached:
            reconciled, src = reconcile_style_color_with_catalog(cached, entry)
            if reconciled != cached:
                upsert_cached_style_color(
                    style_code,
                    reconciled,
                    source=src,
                    image_path=image_str,
                )
            print(
                f"{prefix}[{unit.listing_label}] 缓存款式颜色：{style_code} → {reconciled}",
                flush=True,
            )
            colors[style_code] = reconciled
            continue
        if image:
            print(f"{prefix}[{unit.listing_label}] AI识别款式颜色：{style_code} ← {image.name}", flush=True)
            raw_color = detect_product_color(image, catalog_entry=entry)
            color, src = reconcile_style_color_with_catalog(raw_color, entry)
            if color != raw_color:
                print(
                    f"{prefix}[{unit.listing_label}] 商品表纠偏：{style_code} {raw_color} → {color}",
                    flush=True,
                )
            colors[style_code] = color
            upsert_cached_style_color(
                style_code,
                color,
                source=src,
                image_path=image_str,
            )
        elif entry:
            color = catalog_style_label(entry)
            colors[style_code] = color
            upsert_cached_style_color(
                style_code,
                color,
                source="catalog",
                image_path=image_str,
            )
        else:
            colors[style_code] = style_code
    return colors


def apply_spec_labels_to_sku(
    sku: SkuCombo,
    style_colors: dict[str, str],
    catalog: dict,
    sub_category_cache: dict[str, str],
) -> None:
    sku.style_name = style_colors.get(sku.style_code, sku.style_name or sku.style_code)
    sku.model_name = resolve_size_label(
        sku.style_code,
        sku.model_code,
        catalog,
        sub_category_cache=sub_category_cache,
    )


def enrich_listing_unit_specs(unit: ListingUnit, account_id: str = "") -> None:
    """将 SKU 的款式/尺寸名改为 AI 颜色 + 商品表分组尺寸（全品类通用）。"""
    if not unit.skus:
        return
    if not any(uses_pdd_spec_catalog(sku.style_code) for sku in unit.skus):
        return

    catalog = get_pdd_product_catalog()
    sub_category_cache = build_sub_category_cache(unit, account_id=account_id)
    style_colors = resolve_style_colors(unit, account_id=account_id)
    style_colors = disambiguate_style_colors(style_colors, catalog)
    persist_style_color_cache(unit, style_colors, source="final")

    seen_sizes: list[str] = []
    for sku in unit.skus:
        apply_spec_labels_to_sku(sku, style_colors, catalog, sub_category_cache)
        if sku.model_name not in seen_sizes:
            seen_sizes.append(sku.model_name)

    unit.style_codes = list(dict.fromkeys(sku.style_code for sku in unit.skus))
    unit.model_codes = seen_sizes

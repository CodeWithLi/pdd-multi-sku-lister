"""款式（AI 颜色）+ 尺寸（商品表分组）规格名解析。"""

from __future__ import annotations

import re
from pathlib import Path

from dy_agent.domain.models import ListingUnit, SkuCombo
from dy_agent.llm.vision import (
    detect_product_color,
    disambiguate_conflicting_size_labels_ai,
    _fallback_color_from_catalog,
)
from dy_agent.skills.listing.style_color_cache import get_cached_style_color, upsert_cached_style_color
from dy_agent.skills.listing.pdd_product_catalog import (
    append_product_type_to_size_label,
    catalog_codes_match,
    catalog_has_code,
    fallback_sub_category_from_spec,
    find_catalog_entry,
    get_catalog_entry,
    get_pdd_product_catalog,
    meaningful_product_type_for_label,
    resolve_size_label,
    _norm_code,
)


def uses_pdd_spec_catalog(style_code: str) -> bool:
    return catalog_has_code(style_code)


def _catalog_codes_match(left: str, right: str) -> bool:
    return catalog_codes_match(left, right)


def load_listing_product_catalog() -> dict:
    """与 catalog.parse 一致：优先飞书快照，再统一商品表。"""
    try:
        from dy_agent.skills.listing.catalog import load_product_catalog

        catalog = load_product_catalog()
        if catalog:
            return catalog
    except Exception:
        pass
    return get_pdd_product_catalog()


_MERCHANT_CODE_RE = re.compile(r"^[A-Z]{2,6}\d+[A-Z0-9]*$")


def is_forbidden_spec_code_label(
    label: str,
    *,
    style_code: str = "",
    model_code: str = "",
) -> bool:
    """规格展示名不得使用商品编码（母码/子码）。"""
    text = str(label or "").strip()
    if not text:
        return False
    if style_code and catalog_codes_match(text, style_code):
        return True
    if model_code and catalog_codes_match(text, model_code):
        return True
    from dy_agent.integrations.feishu.listing_feishu_catalog import (
        SUB_SKU_PREFIXES,
        normalize_listing_code,
    )

    norm = normalize_listing_code(text)
    if not norm:
        return False
    if any(norm.startswith(prefix) for prefix in SUB_SKU_PREFIXES):
        return True
    return bool(_MERCHANT_CODE_RE.match(norm))


def _style_label_from_catalog(style_code: str, catalog: dict) -> str:
    entry = find_catalog_entry(catalog, style_code)
    if not entry:
        return ""
    return catalog_style_label(entry)


def _size_label_from_catalog(
    style_code: str,
    model_code: str,
    catalog: dict,
    sub_category_cache: dict[str, str] | None = None,
) -> str:
    label = resolve_size_label(
        style_code,
        model_code,
        catalog,
        sub_category_cache=sub_category_cache,
    )
    if is_forbidden_spec_code_label(label, style_code=style_code, model_code=model_code):
        return ""
    return label


def _unique_style_codes(unit: ListingUnit) -> list[str]:
    return list(dict.fromkeys(sku.style_code for sku in unit.skus if sku.style_code))


def _unit_has_catalog_styles(unit: ListingUnit) -> bool:
    if not unit.skus:
        return False
    catalog = load_listing_product_catalog()
    if not catalog:
        return True
    return any(find_catalog_entry(catalog, sku.style_code) for sku in unit.skus if sku.style_code)


def catalog_style_label(entry) -> str:
    """从商品表颜色规格提取可区分的款式名（AI 重复时兜底）。"""
    color = _fallback_color_from_catalog(entry)
    if color:
        return color
    spec = entry.color_spec.strip()
    if spec:
        return spec[:6]
    ptype = meaningful_product_type_for_label(entry)
    return ptype or ""


def reconcile_style_color_with_catalog(ai_color: str, entry) -> tuple[str, str]:
    """用商品表颜色规格纠偏 AI 识色（尤其浅灰/黑色被误判为白色）。"""
    if not entry:
        return (ai_color or "").strip(), "ai"
    catalog_color = catalog_style_label(entry)
    ai_norm = (ai_color or "").strip()
    if not catalog_color:
        return ai_norm or catalog_style_label(entry), "ai"
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
            entry = find_catalog_entry(catalog, code)
            if entry:
                result[code] = catalog_style_label(entry)

    used: set[str] = set()
    final: dict[str, str] = {}
    for code in colors:
        name = (result.get(code) or "").strip()
        if not name or is_forbidden_spec_code_label(name, style_code=code):
            name = _style_label_from_catalog(code, catalog)
        if not name:
            name = _style_label_from_catalog(code, catalog) or f"款式{len(final)+1}"
        if name in used:
            candidates = [f"{name}-{code[-1]}", _style_label_from_catalog(code, catalog)]
            for cand in candidates:
                cand = (cand or "").strip()
                if cand and cand not in used and not is_forbidden_spec_code_label(cand, style_code=code):
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
    """同套图下某款式编码目录（如 .../第一套图/BD716B 或 BD716B灰色笔袋）。"""
    set_dir = unit.root.parent
    if not set_dir.is_dir():
        return None
    target = str(style_code or "").strip()
    if not target:
        return None
    for path in set_dir.iterdir():
        if path.is_dir() and catalog_codes_match(path.name, target):
            return path
    return None


def _find_style_solo_image(code_dir: Path, style_code: str) -> Path | None:
    """文件夹内与编码同名的单款规格图（BD716A.png），不含组合图。"""
    target = str(style_code or "").strip()
    if not target:
        return None
    for path in sorted(code_dir.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _STYLE_SOLO_EXTS:
            continue
        if catalog_codes_match(path.stem, target):
            return path
    return None


def pick_style_reference_image(unit: ListingUnit, style_code: str) -> Path | None:
    """款式识色专用：仅用 {款式编码}.png，不用组合规格图或主图。"""
    if not str(style_code or "").strip():
        return None

    for sku in unit.skus:
        if not _catalog_codes_match(sku.style_code, style_code):
            continue
        if not _catalog_codes_match(sku.combo_folder, style_code):
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


def build_sub_category_cache(unit: ListingUnit, account_id: str = "", *, allow_ai: bool = True) -> dict[str, str]:
    """
    为单元内子配件解析尺寸子类：仅商品表规则（关键词 → 商品类型 → 规格短名）。
    AI 不在此阶段调用，避免提前改名导致后续撞名消歧、填表对不上；AI 仅在 disambiguate_size_labels 撞名时使用。
    allow_ai 保留参数兼容调用方，此处不使用。
    """
    from dy_agent.skills.listing.pdd_product_catalog import infer_sub_product_category

    catalog = load_listing_product_catalog()
    cache: dict[str, str] = {}
    prefix = f"[{account_id}] " if account_id else ""

    for sku in unit.skus:
        if catalog_codes_match(sku.model_code, sku.style_code):
            continue
        model_entry = find_catalog_entry(catalog, sku.model_code)
        if not model_entry:
            continue
        model_key = _norm_code(model_entry.code)
        if model_key in cache:
            continue

        sub_cat = infer_sub_product_category(model_entry)
        cache[model_key] = sub_cat
        cache[_norm_code(sku.model_code)] = sub_cat
        if prefix:
            print(
                f"{prefix}[{unit.listing_label}] 商品表尺寸子类：{model_key} → {sub_cat}（{model_entry.color_spec}）",
                flush=True,
            )

    return cache


def resolve_style_colors(unit: ListingUnit, account_id: str = "", *, allow_ai: bool = True) -> dict[str, str]:
    catalog = load_listing_product_catalog()
    colors: dict[str, str] = {}
    prefix = f"[{account_id}] " if account_id else ""
    for style_code in _unique_style_codes(unit):
        entry = find_catalog_entry(catalog, style_code)
        cache_code = entry.code if entry else _norm_code(style_code)
        image = pick_style_reference_image(unit, style_code)
        image_str = str(image.resolve()) if image else None
        cached = get_cached_style_color(cache_code or style_code, image_str)
        if cached:
            reconciled, src = reconcile_style_color_with_catalog(cached, entry)
            if reconciled != cached:
                upsert_cached_style_color(
                    cache_code or style_code,
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
        if not allow_ai:
            if entry:
                color = catalog_style_label(entry)
                colors[style_code] = color
                upsert_cached_style_color(
                    cache_code or style_code,
                    color,
                    source="catalog",
                    image_path=image_str,
                )
                print(
                    f"{prefix}[{unit.listing_label}] 商品表款式颜色：{style_code} → {color}",
                    flush=True,
                )
            else:
                colors[style_code] = _style_label_from_catalog(style_code, catalog)
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
                cache_code or style_code,
                color,
                source=src,
                image_path=image_str,
            )
        elif entry:
            color = catalog_style_label(entry)
            colors[style_code] = color
            upsert_cached_style_color(
                cache_code or style_code,
                color,
                source="catalog",
                image_path=image_str,
            )
        else:
            colors[style_code] = _style_label_from_catalog(style_code, catalog)
    return colors


def _style_color_name(style_colors: dict[str, str], style_code: str) -> str:
    if style_code in style_colors:
        return style_colors[style_code]
    for code, name in style_colors.items():
        if catalog_codes_match(code, style_code) and name:
            return name
    return ""


def apply_spec_labels_to_sku(
    sku: SkuCombo,
    style_colors: dict[str, str],
    catalog: dict,
    sub_category_cache: dict[str, str],
) -> None:
    resolved_style = _style_color_name(style_colors, sku.style_code)
    style_name = resolved_style or _style_label_from_catalog(sku.style_code, catalog) or sku.style_name
    if is_forbidden_spec_code_label(style_name, style_code=sku.style_code):
        style_name = _style_label_from_catalog(sku.style_code, catalog)
    sku.style_name = style_name or sku.style_name or ""

    size_name = _size_label_from_catalog(
        sku.style_code,
        sku.model_code,
        catalog,
        sub_category_cache=sub_category_cache,
    )
    if size_name:
        sku.model_name = size_name
    elif not is_forbidden_spec_code_label(sku.model_name, model_code=sku.model_code):
        sku.model_name = sku.model_name or ""


def _combo_skus_for_style(unit: ListingUnit, style_code: str) -> list[SkuCombo]:
    style_norm = style_code.strip().upper()
    return [
        sku
        for sku in unit.skus
        if sku.style_code.strip().upper() == style_norm
        and sku.model_code.strip().upper() != style_norm
    ]


def _group_skus_by_model_name(skus: list[SkuCombo]) -> dict[str, list[SkuCombo]]:
    groups: dict[str, list[SkuCombo]] = {}
    for sku in skus:
        key = (sku.model_name or "").strip()
        groups.setdefault(key, []).append(sku)
    return groups


def _fallback_distinct_size_label(sku: SkuCombo, base_label: str, catalog: dict) -> str:
    """AI/商品类型仍无法区分时，用颜色规格短名或子编码兜底。"""
    code = sku.model_code.strip().upper()
    entry = catalog.get(code) or get_catalog_entry(sku.model_code)
    if entry and entry.color_spec.strip():
        tail = entry.color_spec.strip()
        for prefix in ("亚克力定制款", "亚克力定制", "定制款", "亚克力"):
            if tail.startswith(prefix):
                tail = tail[len(prefix) :].strip()
        tail = tail[:4] if tail else ""
        if tail:
            return append_product_type_to_size_label(
                base_label,
                meaningful_product_type_for_label(entry) or tail,
            )
    tail = fallback_sub_category_from_spec(entry) if entry else ""
    if tail and not is_forbidden_spec_code_label(tail, model_code=sku.model_code):
        return append_product_type_to_size_label(base_label, tail)
    return f"{base_label}-配件"


def refresh_unit_spec_code_lists(unit: ListingUnit) -> None:
    """从 SKU 展示名同步 style_codes / model_codes（槽位对齐后调用）。"""
    unit.style_codes = list(dict.fromkeys(sku.style_code for sku in unit.skus if sku.style_code))
    seen_sizes: list[str] = []
    for sku in unit.skus:
        name = str(sku.model_name or "").strip()
        if name and name not in seen_sizes:
            seen_sizes.append(name)
    unit.model_codes = seen_sizes


def disambiguate_size_labels(
    unit: ListingUnit,
    catalog: dict,
    account_id: str = "",
    *,
    allow_ai: bool = True,
) -> None:
    """
    同款式下若多个子配件落到同一尺寸名，先附加商品类型，仍冲突则 AI 识图区分。
    仅在同一 style_code 内消歧，避免子编码张冠李戴。
    """
    prefix = f"[{account_id}] " if account_id else ""

    for style_code in unit.style_codes:
        combo_skus = _combo_skus_for_style(unit, style_code)
        if len(combo_skus) < 2:
            continue

        by_label = _group_skus_by_model_name(combo_skus)
        for base_label, group in by_label.items():
            if len(group) <= 1:
                continue

            # 第一步：附加商品类型 → 笔袋+挂件(公仔)
            for sku in group:
                code = sku.model_code.strip().upper()
                entry = catalog.get(code) or get_catalog_entry(sku.model_code)
                ptype = meaningful_product_type_for_label(entry)
                if ptype:
                    sku.model_name = append_product_type_to_size_label(base_label, ptype)

            by_typed = _group_skus_by_model_name(group)
            for typed_label, typed_group in by_typed.items():
                if len(typed_group) <= 1:
                    continue

                print(
                    f"{prefix}[{unit.listing_label}] 尺寸名冲突（{style_code}）："
                    f"{typed_label} × {len(typed_group)}，AI 区分…",
                    flush=True,
                )
                ai_map = (
                    disambiguate_conflicting_size_labels_ai(style_code, typed_group, catalog)
                    if allow_ai
                    else {}
                )
                for sku in typed_group:
                    code = sku.model_code.strip().upper()
                    if ai_map.get(code):
                        sku.model_name = ai_map[code]
                        print(
                            f"{prefix}  {code} → {sku.model_name} ← {sku.combo_folder}",
                            flush=True,
                        )

            # 最终仍冲突：颜色规格/编码兜底
            by_final = _group_skus_by_model_name(group)
            for final_label, final_group in by_final.items():
                if len(final_group) <= 1:
                    continue
                for sku in final_group:
                    old = sku.model_name
                    sku.model_name = _fallback_distinct_size_label(sku, base_label, catalog)
                    print(
                        f"{prefix}  兜底区分 {sku.model_code}：{old} → {sku.model_name}",
                        flush=True,
                    )


def enrich_listing_unit_specs(unit: ListingUnit, account_id: str = "", *, allow_ai: bool = True) -> None:
    """将 SKU 的款式/尺寸名改为 AI 颜色 + 商品表分组尺寸（全品类通用）。"""
    if not unit.skus:
        return
    if not _unit_has_catalog_styles(unit):
        return

    catalog = load_listing_product_catalog()
    sub_category_cache = build_sub_category_cache(unit, account_id=account_id, allow_ai=allow_ai)
    style_colors = resolve_style_colors(unit, account_id=account_id, allow_ai=allow_ai)
    style_colors = disambiguate_style_colors(style_colors, catalog)
    persist_style_color_cache(unit, style_colors, source="final")

    seen_sizes: list[str] = []
    for sku in unit.skus:
        apply_spec_labels_to_sku(sku, style_colors, catalog, sub_category_cache)
        if sku.model_name not in seen_sizes:
            seen_sizes.append(sku.model_name)

    disambiguate_size_labels(unit, catalog, account_id=account_id, allow_ai=allow_ai)

    unit.style_codes = list(dict.fromkeys(sku.style_code for sku in unit.skus))
    unit.model_codes = list(dict.fromkeys(sku.model_name for sku in unit.skus))
    dedupe_listing_skus_by_display_spec(unit, account_id=account_id)


def dedupe_listing_skus_by_display_spec(unit: ListingUnit, account_id: str = "") -> None:
    """同一「款式名 + 尺寸名」冲突时编码后缀兜底，不丢弃 SKU。"""
    if not unit.skus:
        return
    prefix = f"[{account_id}] " if account_id else ""
    kept: list[SkuCombo] = []
    seen_keys: set[tuple[str, str]] = set()
    for sku in unit.skus:
        key = (sku.style_name or "", sku.model_name or "")
        if key in seen_keys:
            entry = find_catalog_entry(get_pdd_product_catalog(), sku.model_code)
            tail = fallback_sub_category_from_spec(entry) if entry else "配件"
            sku.model_name = append_product_type_to_size_label(sku.model_name, tail)
            key = (sku.style_name or "", sku.model_name or "")
            if key in seen_keys:
                sku.model_name = f"{sku.model_name}-{len(seen_keys)}"
                key = (sku.style_name or "", sku.model_name or "")
            print(
                f"{prefix}[{unit.listing_label}] 尺寸名兜底：{sku.model_code} → {sku.model_name}",
                flush=True,
            )
        seen_keys.add(key)
        kept.append(sku)
    unit.skus = kept
    unit.style_codes = list(dict.fromkeys(sku.style_code for sku in unit.skus))
    unit.model_codes = list(dict.fromkeys(sku.model_name for sku in unit.skus))

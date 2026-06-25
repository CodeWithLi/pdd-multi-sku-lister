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
from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.base import Skill
from pdd_agent.skills.listing.pdd_product_catalog import (
    BUNDLE_MODEL_CODE,
    ComboPricingError,
    PddProductEntry,
    default_catalog_path,
    get_pdd_product_catalog,
    load_pdd_product_catalog,
    lookup_catalog_spec,
    resolve_combo_pricing,
    resolve_listing_price_scope,
)
from pdd_agent.skills.listing.listing_spec_pipeline import apply_unit_listing_specs

RESERVED_DIRS = frozenset({"主图", "详情页"})
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PREVIEW_NAMES = ("预览图.png", "预览图.jpg", "预览图.jpeg", "预览图.webp")
"""
套图目录命名历史上并不统一：
- 第X套 / 第X套图
- X套 / X套图
- 套图X
- 以及一些后缀：第X套-改版 / 第X套（备用） 等

这里尽量宽松匹配，只要“看起来像套图目录”就纳入 listing targets，
避免前端只显示第一套的问题。
"""
IMAGE_SET_PATTERN = re.compile(
    r"^(?:第?\s*[一二三四五六七八九十\d]+\s*套(?:图)?|套图\s*[一二三四五六七八九十\d]+)(?:[\s\-_（(].*)?$"
)
_PRODUCT_CODE_PREFIX = re.compile(r"^([A-Z0-9]+)")


def _resolve_sku_pricing_or_warn(
    unit: ListingUnit,
    *,
    prefix: str,
    style_code: str,
    model_code: str,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
    bundle_components: list[str] | None = None,
) -> tuple[str, str, str] | None:
    try:
        return resolve_combo_pricing(
            style_code,
            model_code,
            catalog,
            defaults,
            listing_scope=resolve_listing_price_scope(
                family_code=unit.family_code,
                image_set=unit.image_set,
                listing_label=unit.listing_label,
            ),
            bundle_components=bundle_components,
        )
    except ComboPricingError as exc:
        codes = "、".join(exc.invalid_codes or exc.missing_codes)
        if exc.reason == "pricing_invalid":
            unit.warnings.append(
                ListingErrors.Msg.CATALOG_PRICING_INVALID.format(prefix=prefix, codes=codes)
            )
        else:
            unit.warnings.append(
                ListingErrors.Msg.CATALOG_CODE_PRICING_MISSING.format(prefix=prefix, codes=codes)
            )
        return None


def _extract_product_code_prefix(name: str) -> str:
    """从文件夹/文件名前缀提取商品编码，如 BD023A毛绒小狗笔袋 → BD023A。"""
    text = str(name or "").strip()
    if not text:
        return ""
    match = _PRODUCT_CODE_PREFIX.match(text)
    return match.group(1) if match else text


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
    raw = str(name or "").strip()
    # 支持：第X套 / X套 / 套图X / 第X套-改版 / 第X套（备用）
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


def is_image_set_dir(name: str) -> bool:
    return bool(IMAGE_SET_PATTERN.match(name.strip()))


def _load_product_catalog(settings: YamlSettings | None = None) -> dict[str, PddProductEntry]:
    """上架商品数据源：优先飞书「拼多多比价定价」按编码快照，否则本地 Excel。"""
    from pdd_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot
    from pdd_agent.integrations.feishu.config import load_feishu_config
    from pdd_agent.integrations.feishu.pdd_product_catalog_sync import load_unified_pdd_product_catalog

    snapshot = get_listing_feishu_snapshot()
    if snapshot is not None:
        cfg = load_feishu_config()
        catalog = snapshot.product_catalog(cfg)
        if catalog:
            return catalog

    catalog = load_unified_pdd_product_catalog(settings=settings)
    if catalog:
        return catalog

    if settings is not None:
        path = settings.multi_spec.excel_path
        if path.is_file():
            return load_pdd_product_catalog(path)
    default_path = default_catalog_path()
    if default_path.is_file():
        return load_pdd_product_catalog(default_path)
    return {}


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


def _preview_stem_matches_code_dir(stem: str, dir_name: str) -> bool:
    """规格图文件名是否属于该编码文件夹（支持 BD037B+… 匹配 BD037B奶油色长条笔袋）。"""
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
    """
    兄弟目录合并规格图时，只保留与文件夹名匹配的规格图。
    例如 BD037A奶油泡芙笔袋/ 接受 BD037A奶油泡芙笔袋.jpg、BD037A奶油泡芙笔袋+YKL001A.jpg。
    """
    dir_name = code_dir.name.strip()
    if not dir_name:
        return previews
    filtered: list[Path] = []
    for preview in previews:
        stem = preview.stem.strip()
        if stem and _preview_stem_matches_code_dir(stem, dir_name):
            filtered.append(preview)
    return filtered


def _split_combo_stem_parts(stem: str, default_style_code: str = "") -> list[str]:
    """按 + 切段；首段若为文件夹短编码前缀则还原为完整主商品名（含中文）。"""
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


def combo_slot_signature(stem: str, default_style_code: str = "") -> str:
    """槽位对齐签名：单款 / 单配 / 套餐（与中文主商品名、文件名排序无关）。"""
    parsed = _parse_combo_code(stem, default_style_code)
    if not parsed:
        return str(stem or "").strip()
    style, model = parsed
    style_key = style.strip().upper()
    model_key = model.strip().upper()
    if model_key == style_key:
        return "solo"
    if model_key == BUNDLE_MODEL_CODE:
        parts = _split_combo_stem_parts(stem, default_style_code)
        subs = parts[1:] if len(parts) > 1 else []
        return "bundle:" + "+".join(subs)
    return f"combo:{model_key}"


def _preview_sort_key(path: Path, product_code: str):
    """规格图排序：单款 → 单配（按子编码）→ 套餐，避免字母序把套餐/挂件槽位弄反。"""
    parsed = _parse_combo_code(path.stem, product_code)
    if not parsed:
        return (9, "", _natural_sort_key(path))
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
    return (tier, tie, _natural_sort_key(path))


def _find_preview_image(combo_dir: Path) -> Path | None:
    for name in PREVIEW_NAMES:
        p = combo_dir / name
        if p.is_file():
            return p
    imgs = _collect_images(combo_dir)
    return imgs[0] if imgs else None


def _parse_combo_code(name: str, default_style_code: str = "") -> tuple[str, str] | None:
    """解析规格图文件名 → (款式名, 型号名)。按 + 切段，保留中文，与飞书/MinIO 命名一致。

    - ``BD037A奶油泡芙笔袋`` → 单款
    - ``BD037A奶油泡芙笔袋+YKL001A`` → 款式 + 1 个子配件
    - ``BD037A奶油泡芙笔袋+YKL001A+YKL020A+YKL004L`` → 2 个及以上子配件 → 套餐
    - ``BD037B+YKL001N`` + 文件夹 ``BD037B奶油色长条笔袋`` → 首段补全为完整主商品名
    """
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


def _parse_combo_component_codes(name: str, default_style_code: str = "") -> list[str]:
    """规格图文件名 → 参与定价的商品名列表（按 + 切段，保留中文）。"""
    stem = Path(name).stem.strip()
    if not stem:
        return []
    if "+" in stem:
        return list(dict.fromkeys(_split_combo_stem_parts(stem, default_style_code)))
    return [stem]


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


def collect_feishu_catalog_codes_for_targets(
    targets: list[str],
    assets_root: Path,
) -> list[str]:
    """从上架 selector + 素材目录预扫商品编码（款式/型号），供飞书按编码拉取。"""
    from pdd_agent.skills.listing.pdd_product_catalog import _norm_code

    codes: list[str] = []
    for target in targets or []:
        product_selector = _parse_listing_target_product_selector(target)
        if product_selector:
            family_code, image_set, product_code = product_selector
            codes.append(product_code)
            set_dir = assets_root / family_code / image_set
            for sibling_dir in _list_sibling_code_dirs(set_dir):
                codes.append(sibling_dir.name)
                previews = _filter_preview_images_for_code_dir(
                    sibling_dir,
                    sorted(
                        _collect_flat_preview_images(sibling_dir),
                        key=lambda p: _preview_sort_key(p, sibling_dir.name),
                    ),
                )
                for preview in previews:
                    parsed = _parse_combo_code(preview.stem, sibling_dir.name)
                    if parsed:
                        style_code, model_code = parsed
                        codes.extend([style_code, model_code])
            continue

        selector = _parse_listing_target_selector(target)
        if selector:
            family_code, image_set = selector
            codes.append(family_code)
            set_dir = assets_root / family_code / image_set
            for sibling_dir in _list_sibling_code_dirs(set_dir):
                codes.append(sibling_dir.name)
                previews = _filter_preview_images_for_code_dir(
                    sibling_dir,
                    sorted(
                        _collect_flat_preview_images(sibling_dir),
                        key=lambda p: _preview_sort_key(p, sibling_dir.name),
                    ),
                )
                for preview in previews:
                    parsed = _parse_combo_code(preview.stem, sibling_dir.name)
                    if parsed:
                        style_code, model_code = parsed
                        codes.extend([style_code, model_code])
            continue

        codes.append(str(target or "").strip())

    return list(dict.fromkeys(_norm_code(code) for code in codes if _norm_code(code)))


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
            unit.warnings.append(
                ListingErrors.Msg.PREVIEW_FILENAME_UNPARSEABLE.format(prefix=prefix, name=preview.name)
            )
            continue

        style_code, model_code = parsed
        combo_key = (style_code, model_code)
        if combo_key in seen_combo_keys:
            continue
        seen_combo_keys.add(combo_key)

        style_key = style_code.strip().upper()
        model_key = model_code.strip().upper()
        is_bundle = model_key == BUNDLE_MODEL_CODE
        is_combo = model_key != style_key
        style_entry = catalog.get(style_key)
        model_entry = catalog.get(model_key) if is_combo and not is_bundle else style_entry

        if not catalog:
            if not include_excel_missing_previews:
                unit.warnings.append(
                    ListingErrors.Msg.STYLE_NOT_IN_CATALOG_SKIP.format(
                        prefix=prefix, style=style_code, name=preview.name
                    )
                )
                continue
        elif not style_entry:
            if not include_excel_missing_previews:
                unit.warnings.append(
                    ListingErrors.Msg.STYLE_NOT_IN_CATALOG_WARN.format(
                        prefix=prefix, style=style_code, name=preview.name
                    )
                )
                continue
            unit.warnings.append(
                ListingErrors.Msg.STYLE_NOT_IN_CATALOG_DISPLAY.format(
                    prefix=prefix, style=style_code, name=preview.name
                )
            )
        elif is_combo and not is_bundle and not model_entry:
            if not include_excel_missing_previews:
                unit.warnings.append(
                    ListingErrors.Msg.SUBCODE_NOT_IN_CATALOG_SKIP.format(
                        prefix=prefix, model=model_code, name=preview.name
                    )
                )
                continue
            unit.warnings.append(
                ListingErrors.Msg.SUBCODE_NOT_IN_CATALOG_DISPLAY.format(
                    prefix=prefix, model=model_code, name=preview.name
                )
            )

        style_name = lookup_catalog_spec(style_code, catalog) or style_code
        model_name = lookup_catalog_spec(model_code, catalog) or model_code
        if catalog and style_entry:
            style_name = style_code
            if is_bundle:
                model_name = BUNDLE_MODEL_CODE
            else:
                model_name = model_code if is_combo else style_code

        if style_code not in unit.style_codes:
            unit.style_codes.append(style_code)
        if model_code not in unit.model_codes:
            unit.model_codes.append(model_code)

        pricing = _resolve_sku_pricing_or_warn(
            unit,
            prefix=prefix,
            style_code=style_code,
            model_code=model_code,
            catalog=catalog,
            defaults=defaults,
            bundle_components=_parse_combo_component_codes(preview.stem, default_style_code)
            if is_bundle
            else None,
        )
        if pricing is None:
            continue
        inv, gp, sp = pricing
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


def _append_no_sku_material_diagnostics(unit: ListingUnit, sibling_dirs: list[Path]) -> None:
    """无 SKU 时补充素材目录诊断（写入 warnings，供飞书系统原因展示）。"""
    label = unit.listing_label
    if not sibling_dirs:
        unit.warnings.append(f"[{label}] 未找到兄弟款规格目录（路径 {unit.root}）")
        return
    for sibling_dir in sibling_dirs:
        code = sibling_dir.name
        raw_previews = _collect_flat_preview_images(sibling_dir)
        filtered = _filter_preview_images_for_code_dir(sibling_dir, raw_previews)
        if not raw_previews:
            unit.warnings.append(f"[{label}] 目录「{code}」无规格预览图（需非数字命名的 png/jpg）")
            continue
        if not filtered:
            sample = "、".join(p.name for p in raw_previews[:4])
            extra = f" 等共{len(raw_previews)}张" if len(raw_previews) > 4 else ""
            unit.warnings.append(
                f"[{label}] 目录「{code}」有{len(raw_previews)}张图但文件名与编码不匹配"
                f"（如 {sample}{extra}；期望 {code}.png 或 {code}+子编码.png）"
            )
        elif len(filtered) < len(raw_previews):
            unit.warnings.append(
                f"[{label}] 目录「{code}」仅 {len(filtered)}/{len(raw_previews)} 张规格图通过编码过滤"
            )


def parse_new_listing_unit(
    product_code: str,
    unit_root: Path,
    image_set: str,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
    *,
    include_excel_missing_previews: bool = False,
    slot_alignment_test: bool = False,
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
        unit.warnings.append(ListingErrors.Msg.CAROUSEL_MISSING.format(label=label))
    if not unit.detail_images:
        unit.warnings.append(ListingErrors.Msg.DETAIL_MISSING.format(label=label))

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
        _append_no_sku_material_diagnostics(unit, sibling_dirs)
        unit.warnings.append(ListingErrors.Msg.NO_SKU_PARSED.format(label=label))
    else:
        for msg in apply_unit_listing_specs(
            unit,
            allow_ai=False,
            slot_alignment_test=slot_alignment_test,
        ):
            unit.warnings.append(msg)
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
            unit.warnings.append(
                ListingErrors.Msg.STYLE_CODE_MISSING_SKIP.format(label=label, style=style_code)
            )
            continue

        unit.style_codes.append(style_code)

        combo_dirs = sorted(
            (p for p in style_dir.iterdir() if p.is_dir()),
            key=lambda p: p.name,
        )
        for combo_dir in combo_dirs:
            parsed = _parse_combo_code(combo_dir.name, style_code)
            if not parsed:
                unit.warnings.append(
                    ListingErrors.Msg.COMBO_FOLDER_INVALID.format(label=label, folder=combo_dir.name)
                )
                continue

            _, model_code = parsed
            model_name = lookup_catalog_spec(model_code, catalog)
            if model_name is None:
                unit.warnings.append(
                    ListingErrors.Msg.MODEL_CODE_MISSING_SKIP.format(label=label, model=model_code)
                )
                continue

            preview = _find_preview_image(combo_dir)
            if not preview:
                unit.warnings.append(
                    ListingErrors.Msg.PREVIEW_MISSING.format(
                        label=label, style=style_code, combo=combo_dir.name
                    )
                )
                continue

            if model_code not in unit.model_codes:
                unit.model_codes.append(model_code)

            pricing = _resolve_sku_pricing_or_warn(
                unit,
                prefix=f"[{label}]",
                style_code=style_code,
                model_code=model_code,
                catalog=catalog,
                defaults=defaults,
                bundle_components=_parse_combo_component_codes(combo_dir.name, style_code)
                if model_code == BUNDLE_MODEL_CODE
                else None,
            )
            if pricing is None:
                continue
            inv, gp, sp = pricing
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
        unit.warnings.append(ListingErrors.Msg.NO_SKU_PARSED.format(label=label))
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
    assets_root: Path | None = None,
) -> list[ListingUnit]:
    assets_root = assets_root or settings.paths.resolve("assets_root")
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
    slot_alignment_test: bool = False,
    assets_root: Path | None = None,
) -> list[ListingUnit]:
    assets_root = assets_root or settings.paths.resolve("assets_root")
    product_selector = _parse_listing_target_product_selector(target)
    if product_selector:
        family_code, image_set, product_code = product_selector
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
                slot_alignment_test=slot_alignment_test,
            )
        ]

    selector = _parse_listing_target_selector(target)
    if not selector:
        return parse_all_listings(
            target,
            settings,
            include_excel_missing_previews=include_excel_missing_previews,
            assets_root=assets_root,
        )

    family_code, image_set = selector
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
                slot_alignment_test=slot_alignment_test,
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

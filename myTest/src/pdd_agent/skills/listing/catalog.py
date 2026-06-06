"""
多规格目录解析 Skill（确定性逻辑，不经过 LLM）。

Excel 规则：按「款式编码」「型号编码」分别查表，拼单价 = 款式价 + 型号价。
素材结构见 skills/listing/multi_spec.md。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import StructuredTool
from openpyxl import load_workbook

from pdd_agent.core.config import YamlSettings
from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.base import Skill

RESERVED_DIRS = frozenset({"主图", "详情页"})
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PREVIEW_NAMES = ("预览图.png", "预览图.jpg", "预览图.jpeg")
IMAGE_SET_PATTERN = re.compile(r"^第.+套图$")


@dataclass(frozen=True)
class SkuExcelInfo:
    code: str
    name: str
    inventory: int
    price: float


def _natural_sort_key(path: Path):
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def _image_set_sort_key(name: str):
    cn_nums = "零一二三四五六七八九十百千万"
    m = re.search(r"第([一二三四五六七八九十百零\d]+)套图", name)
    if not m:
        return (1, name)
    token = m.group(1)
    if token.isdigit():
        return (0, int(token))
    val = 0
    for ch in token:
        if ch in cn_nums:
            idx = cn_nums.index(ch)
            if idx <= 10:
                val = val * 10 + idx
    return (0, val)


def is_image_set_dir(name: str) -> bool:
    return bool(IMAGE_SET_PATTERN.match(name.strip()))


def _parse_excel_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _parse_excel_float(value, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _format_price(value: float) -> str:
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def load_sku_excel_map(excel_path: Path) -> dict[str, SkuExcelInfo]:
    """读取 sku+名称.xlsx → {SKU编码: SkuExcelInfo}。"""
    if not excel_path.is_file():
        return {}
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active
    mapping: dict[str, SkuExcelInfo] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        code = str(row[0]).strip()
        name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        if not name:
            continue
        mapping[code] = SkuExcelInfo(
            code=code,
            name=name,
            inventory=_parse_excel_int(row[2] if len(row) > 2 else None, 0),
            price=_parse_excel_float(row[3] if len(row) > 3 else None, 0.0),
        )
    wb.close()
    return mapping


def lookup_sku_name(code: str, excel_map: dict[str, SkuExcelInfo]) -> str | None:
    info = excel_map.get((code or "").strip())
    return info.name if info else None


def resolve_combo_pricing(
    style_code: str,
    model_code: str,
    excel_map: dict[str, SkuExcelInfo],
    defaults: dict[str, str],
) -> tuple[str, str, str]:
    fallback_inv = defaults.get("inventory", "10")
    fallback_gp = defaults.get("group_price", "199.9")
    fallback_sp = defaults.get("single_price", "299.9")

    style = excel_map.get(style_code.strip())
    model = excel_map.get(model_code.strip())
    if not style or not model:
        return fallback_inv, fallback_gp, fallback_sp

    inventory = min(style.inventory, model.inventory)
    group_price = style.price + model.price
    single_price = group_price + 100
    return str(inventory), _format_price(group_price), _format_price(single_price)


def list_image_sets(product_code: str, assets_root: Path) -> list[str]:
    root = assets_root / product_code
    if not root.is_dir():
        return []
    sets = [
        d.name
        for d in sorted(root.iterdir(), key=lambda p: _image_set_sort_key(p.name))
        if d.is_dir() and is_image_set_dir(d.name)
    ]
    return sets


def _collect_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
    return sorted(files, key=_natural_sort_key)


def _find_preview_image(combo_dir: Path) -> Path | None:
    for name in PREVIEW_NAMES:
        p = combo_dir / name
        if p.is_file():
            return p
    imgs = _collect_images(combo_dir)
    return imgs[0] if imgs else None


def _parse_combo_folder(folder_name: str) -> tuple[str, str] | None:
    if "+" not in folder_name:
        return None
    left, right = folder_name.split("+", 1)
    left, right = left.strip(), right.strip()
    if not left or not right:
        return None
    return left, right


def parse_listing_unit(
    product_code: str,
    unit_root: Path,
    image_set: str,
    excel_map: dict[str, SkuExcelInfo],
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
        style_name = lookup_sku_name(style_code, excel_map)
        if style_name is None:
            unit.warnings.append(f"[{label}] Excel 无款式编码 [{style_code}]，跳过")
            continue

        unit.style_codes.append(style_code)

        combo_dirs = sorted(
            (p for p in style_dir.iterdir() if p.is_dir() and "+" in p.name),
            key=lambda p: p.name,
        )
        for combo_dir in combo_dirs:
            parsed = _parse_combo_folder(combo_dir.name)
            if not parsed:
                unit.warnings.append(f"[{label}] 组合文件夹格式错误: {combo_dir.name}")
                continue

            _, model_code = parsed
            model_name = lookup_sku_name(model_code, excel_map)
            if model_name is None:
                unit.warnings.append(f"[{label}] Excel 无型号编码 [{model_code}]，跳过")
                continue

            preview = _find_preview_image(combo_dir)
            if not preview:
                unit.warnings.append(f"[{label}] 缺少预览图: {style_code}/{combo_dir.name}")
                continue

            inv, gp, sp = resolve_combo_pricing(style_code, model_code, excel_map, defaults)
            if model_code not in unit.model_codes:
                unit.model_codes.append(model_code)

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


def parse_all_listings(product_code: str, settings: YamlSettings) -> list[ListingUnit]:
    assets_root = settings.paths.resolve("assets_root")
    excel_map = load_sku_excel_map(settings.multi_spec.excel_path)
    defaults = settings.multi_spec.defaults
    product_root = assets_root / product_code
    if not product_root.is_dir():
        return []

    image_sets = list_image_sets(product_code, assets_root)
    if image_sets:
        return [
            parse_listing_unit(product_code, product_root / s, s, excel_map, defaults)
            for s in image_sets
        ]
    return [parse_listing_unit(product_code, product_root, "", excel_map, defaults)]


def list_product_codes(settings: YamlSettings) -> list[str]:
    assets_root = settings.paths.resolve("assets_root")
    if not assets_root.is_dir():
        return []
    return sorted(d.name for d in assets_root.iterdir() if d.is_dir() and not d.name.startswith("."))


class CatalogSkill(Skill):
    name = "parse_catalog"
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

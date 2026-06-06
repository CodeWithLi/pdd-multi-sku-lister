"""
多规格目录解析 Skill（确定性逻辑，不经过 LLM）。

素材结构见 skills/listing/multi_spec.md：
  商品编码 / 第x套图 / 主图|详情页|款式文件夹 / 预览图
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import StructuredTool
from openpyxl import load_workbook

from pdd_agent.core.config import YamlSettings
from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.base import Skill

# 非款式目录，扫描时需跳过
RESERVED_DIRS = frozenset({"主图", "详情页"})
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PREVIEW_NAMES = ("预览图.png", "预览图.jpg", "预览图.jpeg")
# 匹配「第一套图」「第二套图」等
IMAGE_SET_PATTERN = re.compile(r"^第.+套图$")


def _natural_sort_key(path: Path):
    """文件名自然排序：1.png, 2.png, …, 10.png。"""
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def is_image_set_dir(name: str) -> bool:
    """判断目录名是否为「第x套图」。"""
    return bool(IMAGE_SET_PATTERN.match(name.strip()))


def list_image_sets(product_code: str, assets_root: Path) -> list[str]:
    """列出商品下所有套图文件夹名。"""
    root = assets_root / product_code
    if not root.is_dir():
        return []
    return sorted(
        [d.name for d in root.iterdir() if d.is_dir() and is_image_set_dir(d.name)],
        key=lambda n: n,
    )


def _collect_images(folder: Path) -> list[Path]:
    """收集文件夹内图片并按自然序排序。"""
    if not folder.is_dir():
        return []
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
    return sorted(files, key=_natural_sort_key)


def _find_preview(style_dir: Path) -> Path | None:
    """
    在款式目录下查找 SKU 预览图。
    优先 预览图.png；否则取组合文件夹内任意图片。
    """
    for combo in style_dir.iterdir():
        if not combo.is_dir():
            continue
        for name in PREVIEW_NAMES:
            candidate = combo / name
            if candidate.is_file():
                return candidate
        for f in combo.iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                return f
    return None


def load_sku_excel(excel_path: Path) -> dict[str, tuple[str, str, str]]:
    """
    读取 sku+名称.xlsx。
    返回: 文件夹名 -> (中文规格名, 库存, 拼单价)
    """
    if not excel_path.is_file():
        return {}
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active
    mapping: dict[str, tuple[str, str, str]] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        code = str(row[0]).strip()
        name = str(row[1]).strip() if len(row) > 1 and row[1] else code
        inv = str(row[2]).strip() if len(row) > 2 and row[2] is not None else "10"
        price = str(row[3]).strip() if len(row) > 3 and row[3] is not None else "199.9"
        mapping[code] = (name, inv, price)
    wb.close()
    return mapping


def parse_listing_unit(
    product_code: str,
    unit_root: Path,
    image_set: str,
    excel_map: dict[str, tuple[str, str, str]],
    defaults: dict[str, str],
) -> ListingUnit:
    """解析单个上架单元（一套图）下的主图、详情、SKU 组合。"""
    unit = ListingUnit(product_code=product_code, image_set=image_set, root=unit_root)
    unit.carousel_images = _collect_images(unit_root / "主图")
    unit.detail_images = _collect_images(unit_root / "详情页")

    # 款式文件夹：排除主图/详情页/套图目录
    style_dirs = [
        d
        for d in unit_root.iterdir()
        if d.is_dir() and d.name not in RESERVED_DIRS and not is_image_set_dir(d.name)
    ]
    for style_dir in sorted(style_dirs, key=lambda p: p.name):
        style_code = style_dir.name
        unit.style_codes.append(style_code)
        for combo_dir in sorted(style_dir.iterdir(), key=lambda p: p.name):
            if not combo_dir.is_dir():
                continue
            folder_name = combo_dir.name
            # 文件夹名如 BD046A+YKL2005A，+ 后为型号编码
            if "+" in folder_name:
                _, model_code = folder_name.split("+", 1)
            else:
                model_code = folder_name
            if model_code not in unit.model_codes:
                unit.model_codes.append(model_code)

            excel_key = folder_name
            info = excel_map.get(excel_key)
            if not info:
                unit.warnings.append(f"Excel 未找到: {excel_key}")
                continue

            preview = _find_preview(style_dir)
            if not preview:
                unit.warnings.append(f"缺少预览图: {folder_name}")
                continue

            name, inv, gp = info
            unit.skus.append(
                SkuCombo(
                    style_code=style_code,
                    style_name=name.split("+")[0] if "+" in name else style_code,
                    model_code=model_code,
                    model_name=name,
                    combo_folder=folder_name,
                    preview_image=preview,
                    inventory=inv or defaults.get("inventory", "10"),
                    group_price=gp or defaults.get("group_price", "199.9"),
                    single_price=defaults.get("single_price", "299.9"),
                )
            )
    return unit


def parse_all_listings(product_code: str, settings: YamlSettings) -> list[ListingUnit]:
    """
    解析某商品编码下的全部上架单元。
    有「第x套图」时每个套图一个单元；否则整目录视为一套。
    """
    assets_root = settings.paths.resolve("assets_root")
    excel_map = load_sku_excel(settings.multi_spec.excel_path)
    defaults = settings.multi_spec.defaults
    product_root = assets_root / product_code
    if not product_root.is_dir():
        return []

    image_sets = list_image_sets(product_code, assets_root)
    if image_sets:
        units = []
        for image_set in image_sets:
            units.append(
                parse_listing_unit(
                    product_code,
                    product_root / image_set,
                    image_set,
                    excel_map,
                    defaults,
                )
            )
        return units

    # 兼容无套图子目录的旧结构
    return [parse_listing_unit(product_code, product_root, "", excel_map, defaults)]


class CatalogSkill(Skill):
    """LangChain Tool：供 Agent 查询某商品可解析出多少上架单元。"""

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

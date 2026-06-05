"""
多规格测试素材目录解析。

结构示例::

    多规格测试/
      sku+名称.xlsx
      BD046A/                      # 商品组
        第一套图/                  # 一套图 = 一个上架商品
          主图/  1.png … 5.png
          详情页/ 6.png … 8.png
          BD046A/                  # 款式
            BD046A+YKL2005A/
              预览图.png
        第二套图/                  # 另一套图 = 另一个商品
          ...

    兼容旧结构（无「第x套图」时，商品目录本身即一个上架单元）::

      BD199A/
        主图/
        详情页/
        BD199A/
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from openpyxl import load_workbook

from pdd_auto.paths import PROJECT_ROOT

RESERVED_DIRS = frozenset({"主图", "详情页"})
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PREVIEW_NAMES = ("预览图.png", "预览图.jpg", "预览图.jpeg")
IMAGE_SET_PATTERN = re.compile(r"^第.+套图$")


@dataclass
class SkuCombo:
    style_code: str
    style_name: str
    model_code: str
    model_name: str
    combo_folder: str
    preview_image: Path


@dataclass
class MultiSpecProduct:
    product_code: str
    root: Path
    image_set: str = ""
    carousel_images: list[Path] = field(default_factory=list)
    detail_images: list[Path] = field(default_factory=list)
    style_codes: list[str] = field(default_factory=list)
    model_codes: list[str] = field(default_factory=list)
    skus: list[SkuCombo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def listing_label(self) -> str:
        if self.image_set:
            return f"{self.product_code}/{self.image_set}"
        return self.product_code


def _natural_sort_key(path: Path):
    name = path.name.lower()
    parts = re.split(r"(\d+)", name)
    return [int(p) if p.isdigit() else p for p in parts]


def _image_set_sort_key(name: str):
    """第一套图、第二套图 … 按中文序号排序。"""
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
            elif ch == "百":
                val = max(val, 1) * 100
            elif ch == "千":
                val = max(val, 1) * 1000
    return (0, val)


def is_image_set_dir(name: str) -> bool:
    return bool(IMAGE_SET_PATTERN.match(name.strip()))


def multi_spec_root(config: dict | None = None) -> Path:
    cfg = (config or {}).get("multi_spec") or {}
    rel = (cfg.get("root") or "多规格测试").strip()
    return (PROJECT_ROOT / rel).resolve()


def excel_path(config: dict | None = None) -> Path:
    cfg = (config or {}).get("multi_spec") or {}
    rel = (cfg.get("excel") or "多规格测试/sku+名称.xlsx").strip()
    return (PROJECT_ROOT / rel).resolve()


def load_sku_name_map(config: dict | None = None) -> dict[str, str]:
    """读取 sku+名称.xlsx → {SKU编码: 中文名}。"""
    path = excel_path(config)
    if not path.is_file():
        raise FileNotFoundError(f"未找到 SKU 名称表：{path}")

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    mapping: dict[str, str] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        code = str(row[0]).strip()
        name = str(row[1]).strip() if row[1] else ""
        if name:
            mapping[code] = name
    wb.close()
    return mapping


def lookup_sku_name(code: str, name_map: dict[str, str]) -> str | None:
    code = (code or "").strip()
    if not code:
        return None
    return name_map.get(code)


def _list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
    files.sort(key=_natural_sort_key)
    return files


def _find_preview_image(combo_dir: Path) -> Path | None:
    for name in PREVIEW_NAMES:
        p = combo_dir / name
        if p.is_file():
            return p
    imgs = _list_images(combo_dir)
    return imgs[0] if imgs else None


def _parse_combo_folder(folder_name: str) -> tuple[str, str] | None:
    text = folder_name.strip()
    if "+" not in text:
        return None
    left, right = text.split("+", 1)
    left, right = left.strip(), right.strip()
    if not left or not right:
        return None
    return left, right


def resolve_account_product_codes(account_config: dict) -> list[str]:
    """读取店铺待上架商品编码列表；未选则返回空列表。"""
    ms = account_config.get("multi_spec") or {}
    raw = ms.get("product_codes")
    if isinstance(raw, list):
        return list(dict.fromkeys(str(c).strip() for c in raw if str(c).strip()))
    legacy = (ms.get("product_code") or account_config.get("product_code") or "").strip()
    return [legacy] if legacy else []


def list_products(config: dict | None = None) -> list[str]:
    root = multi_spec_root(config)
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def list_image_sets(product_code: str, config: dict | None = None) -> list[str]:
    """返回商品下所有套图文件夹名；无套图时返回 ['']（表示商品根目录本身）。"""
    product_dir = multi_spec_root(config) / product_code
    if not product_dir.is_dir():
        return []
    sets = [
        p.name
        for p in sorted(product_dir.iterdir(), key=lambda x: _image_set_sort_key(x.name))
        if p.is_dir() and is_image_set_dir(p.name)
    ]
    return sets if sets else [""]


def resolve_listing_dirs(product_dir: Path) -> list[tuple[Path, str]]:
    """
    解析上架单元目录。
    有「第x套图」→ 每套图一个商品；否则商品根目录即一个商品。
    """
    image_sets = sorted(
        (p for p in product_dir.iterdir() if p.is_dir() and is_image_set_dir(p.name)),
        key=lambda p: _image_set_sort_key(p.name),
    )
    if image_sets:
        return [(p, p.name) for p in image_sets]
    return [(product_dir, "")]


def _parse_listing_dir(
    listing_dir: Path,
    product_code: str,
    image_set: str,
    name_map: dict[str, str],
    _log: Callable[[str], None],
) -> MultiSpecProduct:
    warnings: list[str] = []
    label = f"{product_code}/{image_set}" if image_set else product_code

    carousel = _list_images(listing_dir / "主图")
    detail = _list_images(listing_dir / "详情页")
    if not carousel:
        msg = f"[{label}] 主图文件夹为空：{listing_dir / '主图'}"
        warnings.append(msg)
        _log(f"[警告] {msg}")
    if not detail:
        msg = f"[{label}] 详情页文件夹为空：{listing_dir / '详情页'}"
        warnings.append(msg)
        _log(f"[警告] {msg}")

    skus: list[SkuCombo] = []
    style_codes: list[str] = []
    model_codes: list[str] = []

    style_dirs = sorted(
        (p for p in listing_dir.iterdir() if p.is_dir() and p.name not in RESERVED_DIRS),
        key=lambda p: p.name,
    )

    for style_dir in style_dirs:
        if is_image_set_dir(style_dir.name):
            continue

        style_code = style_dir.name
        style_name = lookup_sku_name(style_code, name_map)
        if style_name is None:
            msg = (
                f"[{label}] Excel 中无此商品编码（款式）[{style_code}]，"
                f"跳过文件夹 {style_code}/"
            )
            warnings.append(msg)
            _log(f"[警告] {msg}")
            continue

        style_codes.append(style_code)

        combo_dirs = sorted(
            (p for p in style_dir.iterdir() if p.is_dir() and "+" in p.name),
            key=lambda p: p.name,
        )
        for combo_dir in combo_dirs:
            parsed = _parse_combo_folder(combo_dir.name)
            if not parsed:
                msg = (
                    f"[{label}] 组合文件夹名格式错误（须含 '+'）："
                    f"{style_code}/{combo_dir.name}，已跳过"
                )
                warnings.append(msg)
                _log(f"[警告] {msg}")
                continue

            _, model_code = parsed
            model_name = lookup_sku_name(model_code, name_map)
            if model_name is None:
                msg = (
                    f"[{label}] Excel 中无此商品编码（型号）[{model_code}]，"
                    f"跳过 {style_code}/{combo_dir.name}"
                )
                warnings.append(msg)
                _log(f"[警告] {msg}")
                continue

            preview = _find_preview_image(combo_dir)
            if not preview:
                msg = f"[{label}] 缺少预览图，跳过 {style_code}/{combo_dir.name}"
                warnings.append(msg)
                _log(f"[警告] {msg}")
                continue

            if model_code not in model_codes:
                model_codes.append(model_code)
            skus.append(
                SkuCombo(
                    style_code=style_code,
                    style_name=style_name,
                    model_code=model_code,
                    model_name=model_name,
                    combo_folder=combo_dir.name,
                    preview_image=preview,
                )
            )

    if not skus:
        msg = f"[{label}] 未解析到任何有效 SKU 组合（均已跳过或目录为空）"
        warnings.append(msg)
        _log(f"[警告] {msg}")

    return MultiSpecProduct(
        product_code=product_code,
        image_set=image_set,
        root=listing_dir,
        carousel_images=carousel,
        detail_images=detail,
        style_codes=style_codes,
        model_codes=model_codes,
        skus=skus,
        warnings=warnings,
    )


def parse_all_listings(
    product_code: str,
    config: dict | None = None,
    name_map: dict[str, str] | None = None,
    log: Callable[[str], None] | None = None,
) -> list[MultiSpecProduct]:
    """
    解析商品下全部上架单元（每套图一个）。
    返回至少 attempted 的 MultiSpecProduct 列表（含 SKU 为空的也会返回，由 validate 过滤）。
    """
    _log = log or print
    root = multi_spec_root(config)
    product_dir = root / product_code
    if not product_dir.is_dir():
        _log(f"[警告] 商品目录不存在：{product_dir}，跳过商品 [{product_code}]")
        return []

    if name_map is None:
        name_map = load_sku_name_map(config)

    listing_dirs = resolve_listing_dirs(product_dir)
    if len(listing_dirs) > 1:
        _log(f"商品 [{product_code}] 共 {len(listing_dirs)} 套图，将分别作为独立商品上架")

    results: list[MultiSpecProduct] = []
    for listing_dir, image_set in listing_dirs:
        if image_set:
            _log(f"--- 解析套图：{product_code}/{image_set} ---")
        product = _parse_listing_dir(
            listing_dir, product_code, image_set, name_map, _log
        )
        results.append(product)
    return results


def parse_product(
    product_code: str,
    config: dict | None = None,
    name_map: dict[str, str] | None = None,
    log: Callable[[str], None] | None = None,
    image_set: str | None = None,
) -> MultiSpecProduct | None:
    """
    解析单个上架单元。
    image_set 为空则解析第一套（或唯一一套）；指定则解析该套图。
    """
    listings = parse_all_listings(product_code, config, name_map, log)
    if not listings:
        return None
    if image_set:
        for p in listings:
            if p.image_set == image_set:
                return p
        (log or print)(f"[警告] 未找到套图 [{image_set}]，跳过")
        return None
    return listings[0]


def validate_product(product: MultiSpecProduct) -> list[str]:
    if not product.skus:
        return [f"[{product.listing_label}] Excel 中未能匹配到任何可上架 SKU"]
    return []

"""商品素材：品类/编码/款式路径解析，1.jpg～8.jpg 轮播与详情图。"""
from __future__ import annotations

import os
import re
from pathlib import Path

from pdd_auto.paths import PRODUCTS_DIR

DEFAULT_VARIANT = "default"
CAROUSEL_START = 1
CAROUSEL_END = 5
DETAIL_START = 6
DETAIL_END = 8
IMAGE_EXT = ".jpg"


def load_asset_rules(config: dict | None) -> dict:
    """读取 config 中的 product_assets 规则，缺省为 1-5 轮播、6-8 详情、.jpg。"""
    raw = (config or {}).get("product_assets") or {}
    carousel = raw.get("carousel") or list(range(CAROUSEL_START, CAROUSEL_END + 1))
    detail = raw.get("detail") or list(range(DETAIL_START, DETAIL_END + 1))
    return {
        "carousel": [int(x) for x in carousel],
        "detail": [int(x) for x in detail],
        "ext": (raw.get("ext") or IMAGE_EXT).lower(),
        "default_variant": (raw.get("default_variant") or DEFAULT_VARIANT).strip() or DEFAULT_VARIANT,
    }


def build_product_relative_path(category: str, code: str, variant: str) -> str:
    """组装相对路径：products/品类/编码/款式。"""
    cat = (category or "").strip()
    prod_code = (code or "").strip()
    var = (variant or DEFAULT_VARIANT).strip() or DEFAULT_VARIANT
    if not cat or not prod_code:
        raise ValueError("商品素材配置缺少 category 或 code")
    return f"products/{cat}/{prod_code}/{var}"


def resolve_account_product_path(account: dict, config: dict | None = None) -> str:
    """
    解析店铺素材目录（相对项目根的路径字符串）。

    优先 account.product { category, code, variant }；
    兼容旧字段 product_path（若已含款式层则直接用，否则尝试补 default）。
    """
    product_cfg = account.get("product") or {}
    category = (product_cfg.get("category") or "").strip()
    code = (product_cfg.get("code") or "").strip()
    rules = load_asset_rules(config)

    if category and code:
        variant = (product_cfg.get("variant") or rules["default_variant"]).strip()
        if not variant:
            variant = rules["default_variant"]
        return build_product_relative_path(category, code, variant)

    legacy = (account.get("product_path") or "").strip()
    if legacy:
        return legacy

    raise ValueError(
        f"[{account.get('account_id', '?')}] 未配置商品素材："
        "请进行填写"
    )


def resolve_account_product_abs_path(account: dict, config: dict | None = None) -> Path:
    rel = resolve_account_product_path(account, config)
    return (PRODUCTS_DIR.parent / rel).resolve()


def _image_filename(index: int, ext: str = IMAGE_EXT) -> str:
    return f"{index}{ext}"


def _abs_image_path(folder: Path, index: int, ext: str = IMAGE_EXT) -> Path:
    return folder / _image_filename(index, ext)


def get_carousel_images(
    folder_path: str | Path,
    config: dict | None = None,
) -> list[str]:
    """返回轮播主图绝对路径列表（默认 1.jpg～5.jpg）。"""
    rules = load_asset_rules(config)
    folder = Path(folder_path)
    paths = []
    for i in rules["carousel"]:
        p = _abs_image_path(folder, i, rules["ext"])
        if p.is_file():
            paths.append(str(p.resolve()))
    return paths


def get_detail_images(
    folder_path: str | Path,
    config: dict | None = None,
) -> list[str]:
    """返回详情图绝对路径列表（默认 6.jpg～8.jpg）。"""
    rules = load_asset_rules(config)
    folder = Path(folder_path)
    paths = []
    for i in rules["detail"]:
        p = _abs_image_path(folder, i, rules["ext"])
        if p.is_file():
            paths.append(str(p.resolve()))
    return paths


def get_first_carousel_path(folder_path: str | Path, config: dict | None = None) -> str | None:
    images = get_carousel_images(folder_path, config)
    return images[0] if images else None


def get_first_detail_path(folder_path: str | Path, config: dict | None = None) -> str | None:
    images = get_detail_images(folder_path, config)
    return images[0] if images else None


def validate_product_images(
    folder_path: str | Path,
    config: dict | None = None,
) -> tuple[bool, list[str]]:
    """
    校验款式文件夹内轮播 + 详情图是否齐全。
    返回 (是否通过, 错误信息列表)。
    """
    rules = load_asset_rules(config)
    folder = Path(folder_path)
    errors: list[str] = []

    if not folder.is_dir():
        return False, [f"素材目录不存在：{folder}"]

    for i in rules["carousel"]:
        p = _abs_image_path(folder, i, rules["ext"])
        if not p.is_file():
            errors.append(f"缺少轮播主图：{p.name}（1～5 为商品轮播图）")

    for i in rules["detail"]:
        p = _abs_image_path(folder, i, rules["ext"])
        if not p.is_file():
            errors.append(f"缺少详情图：{p.name}（6～8 为商品详情图）")

    return len(errors) == 0, errors


def list_variants(category: str, code: str) -> list[str]:
    """列出 products/品类/编码/ 下所有款式子文件夹名。"""
    base = PRODUCTS_DIR / category / code
    if not base.is_dir():
        return []
    variants = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            variants.append(child.name)
    return variants


def list_product_codes(category: str) -> list[str]:
    """列出品类下所有商品编码文件夹。"""
    base = PRODUCTS_DIR / category
    if not base.is_dir():
        return []
    return sorted(
        child.name
        for child in base.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    )


def list_categories() -> list[str]:
    """列出 products 下所有品类文件夹。"""
    if not PRODUCTS_DIR.is_dir():
        return []
    return sorted(
        child.name
        for child in PRODUCTS_DIR.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    )


def list_sku_images(folder_path: str | Path) -> list[str]:
    """列出款式文件夹内 sku_ 开头的预览图文件名。"""
    folder = Path(folder_path)
    if not folder.is_dir():
        return []
    names = []
    for f in folder.iterdir():
        if not f.is_file():
            continue
        if f.name.startswith("sku_") and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
            names.append(f.name)
    return sorted(names, key=_natural_sort_key)


def _natural_sort_key(name: str):
    parts = re.split(r"(\d+)", name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def migrate_account_product_fields(account: dict, config: dict | None = None) -> dict:
    """
    确保 account 含 product 字段；若仅有旧 product_path 则尝试解析。
    返回更新后的 product 字典（不写盘）。
    """
    rules = load_asset_rules(config)
    product = dict(account.get("product") or {})
    legacy = (account.get("product_path") or "").strip()

    if product.get("category") and product.get("code"):
        if not product.get("variant"):
            product["variant"] = rules["default_variant"]
        return product

    if legacy:
        # products/挂件/BCP001/default 或 products/挂件/BCP001
        parts = Path(legacy.replace("\\", "/")).parts
        try:
            idx = parts.index("products")
            rest = parts[idx + 1 :]
        except ValueError:
            rest = parts

        if len(rest) >= 2:
            product.setdefault("category", rest[0])
            product.setdefault("code", rest[1])
            if len(rest) >= 3:
                product.setdefault("variant", rest[2])
            else:
                product.setdefault("variant", rules["default_variant"])
            return product

    product.setdefault("category", "")
    product.setdefault("code", "")
    product.setdefault("variant", rules["default_variant"])
    return product

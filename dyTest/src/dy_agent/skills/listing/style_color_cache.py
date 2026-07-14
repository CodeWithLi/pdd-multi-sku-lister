"""款式颜色 DB 缓存占位（抖店版暂未落库，始终走商品表/AI）。"""

from __future__ import annotations


def get_cached_style_color(product_code: str, image_path: str | None = None) -> str | None:
    _ = product_code, image_path
    return None


def upsert_cached_style_color(
    product_code: str,
    color: str,
    *,
    source: str = "",
    image_path: str | None = None,
) -> None:
    _ = product_code, color, source, image_path

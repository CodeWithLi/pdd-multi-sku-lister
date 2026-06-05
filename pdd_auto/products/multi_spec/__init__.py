"""多规格测试目录：款式 + 型号 + 预览图。"""
from pdd_auto.products.multi_spec.catalog import (
    SkuCombo,
    MultiSpecProduct,
    load_sku_name_map,
    parse_product,
    parse_all_listings,
    list_image_sets,
    list_products,
    resolve_account_product_codes,
)

__all__ = [
    "SkuCombo",
    "MultiSpecProduct",
    "load_sku_name_map",
    "parse_product",
    "parse_all_listings",
    "list_image_sets",
    "list_products",
    "resolve_account_product_codes",
]

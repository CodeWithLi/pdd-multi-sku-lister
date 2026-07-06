"""上架商品属性字段定义与默认种子数据。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListingProductAttributeSeed:
    field_key: str
    label: str
    selected_value: str
    options: tuple[str, ...]
    enabled: bool
    sort_order: int


DEFAULT_LISTING_PRODUCT_ATTRIBUTES: tuple[ListingProductAttributeSeed, ...] = (
    ListingProductAttributeSeed("brand", "品牌", "无品牌/无注册商标", ("无品牌/无注册商标",), True, 10),
    ListingProductAttributeSeed("material", "重要材质", "帆布", ("帆布",), True, 20),
    ListingProductAttributeSeed("feature", "特点", "大容量", ("大容量",), True, 30),
    ListingProductAttributeSeed("gender", "适用性别", "通用", ("通用",), True, 40),
    ListingProductAttributeSeed("age_group", "适用年龄段", "6岁以上", ("6岁以上",), True, 50),
    ListingProductAttributeSeed("style", "风格", "可爱", ("可爱",), True, 60),
    ListingProductAttributeSeed("transparent", "是否透明", "", (), False, 70),
    ListingProductAttributeSeed("closure", "闭合方式", "系带", ("系带",), True, 80),
    ListingProductAttributeSeed("has_layer", "是否有夹层", "", (), False, 90),
    ListingProductAttributeSeed("waterproof", "是否防水", "不防水", ("不防水",), True, 100),
    ListingProductAttributeSeed("trend", "流行元素", "少女心", ("少女心",), True, 110),
    ListingProductAttributeSeed("audience", "适用人群", "通用", ("通用",), True, 120),
    ListingProductAttributeSeed("scenario", "适用场景", "开学季", ("开学季",), True, 130),
    ListingProductAttributeSeed("product_type", "产品类型", "", (), False, 140),
    ListingProductAttributeSeed("pattern", "图案", "卡通动漫", ("卡通动漫",), True, 150),
    ListingProductAttributeSeed("packaging", "包装方式", "简装", ("简装",), True, 160),
)

"""上架场景飞书「拼多多比价定价」匹配：保留套图文件夹全名，不做中文截断。"""

from __future__ import annotations

from typing import Any

from pdd_agent.skills.campaign.price_rules import normalize_price_code, price_rule_candidates
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry, _norm_code

# 子 SKU 控价/商品表编码前缀（如 YKL001N）；母商品文件夹名不在此列
SUB_SKU_PREFIXES = ("YKL", "GJ", "AXBD", "BJB", "YKB", "MK")


def normalize_listing_code(raw: str) -> str:
    """套图下文件夹名 / 飞书商品编码：去空白、统一大写，保留中文后缀。"""
    return _norm_code(raw)


def is_sub_sku_code(code: str, merchant_code: str = "") -> bool:
    """是否子 SKU 编码（YKL/GJ/AXBD 等），兄弟款母商品码不算子编码。"""
    norm = normalize_listing_code(code)
    merchant = normalize_listing_code(merchant_code)
    if not norm:
        return False
    if merchant and codes_match(norm, merchant):
        return False
    return any(norm.startswith(prefix) for prefix in SUB_SKU_PREFIXES)


def feishu_snapshot_alias_allowed(pending: str, raw_code: str) -> bool:
    """短编码飞书行（如 BD025A）不能顶替待查的长文件夹名（BD025A面包小狗笔袋）。"""
    pending_code = normalize_listing_code(pending)
    raw = normalize_listing_code(raw_code)
    if not pending_code or not raw:
        return False
    if pending_code == raw:
        return True
    if not codes_match(pending_code, raw):
        return False
    return len(raw) >= len(pending_code)


def codes_match(left: str, right: str) -> bool:
    """两侧编码是否指向同一飞书行（全名 / 前缀 / 归一化码）。"""
    from pdd_agent.skills.campaign.price_rules import _compact_code_hyphen

    a = normalize_listing_code(left)
    b = normalize_listing_code(right)
    if not a or not b:
        return False
    if a == b or a.startswith(b) or b.startswith(a):
        return True
    if _compact_code_hyphen(a) == _compact_code_hyphen(b):
        return True
    return normalize_price_code(a) == normalize_price_code(b)


def snapshot_record_fields(snapshot: Any, code: str) -> dict[str, Any] | None:
    """按上架编码在快照中找飞书行（精确 → 前缀 → 归一化）。"""
    if snapshot is None:
        return None
    records: dict[str, dict[str, Any]] = getattr(snapshot, "records_by_code", None) or {}
    key = normalize_listing_code(code)
    if not key:
        return None
    if key in records:
        return records[key]
    for candidate in price_rule_candidates(key):
        if candidate in records:
            return records[candidate]
    for stored_key, fields in records.items():
        if codes_match(key, stored_key):
            return fields
    return None


def catalog_entry(catalog: dict[str, PddProductEntry], code: str) -> PddProductEntry | None:
    """在商品 catalog 中按上架编码查找条目。"""
    key = normalize_listing_code(code)
    if not key:
        return None
    if key in catalog:
        return catalog[key]
    for candidate in price_rule_candidates(key):
        if candidate in catalog:
            return catalog[candidate]
    for stored_key, entry in catalog.items():
        if codes_match(key, stored_key):
            return entry
    return None


def collect_warm_codes_from_units(units: list[Any], *, extra_codes: list[str] | None = None) -> list[str]:
    """收集需拉取飞书的编码：母商品文件夹名 + 子 SKU 型号码。"""
    codes: list[str] = []
    for unit in units or []:
        merchant = normalize_listing_code(getattr(unit, "product_code", ""))
        if merchant:
            codes.append(merchant)
        for raw in getattr(unit, "model_codes", None) or []:
            text = normalize_listing_code(raw)
            if text and is_sub_sku_code(text, merchant):
                codes.append(text)
    for raw in extra_codes or []:
        text = normalize_listing_code(raw)
        if text:
            codes.append(text)
    return list(dict.fromkeys(codes))


def collect_sub_sku_codes(unit: Any) -> list[str]:
    """上架单元内需要去飞书查控价/商品表的子 SKU 编码。"""
    merchant = normalize_listing_code(getattr(unit, "product_code", ""))
    result: list[str] = []
    for raw in getattr(unit, "model_codes", None) or []:
        code = normalize_listing_code(raw)
        if code and is_sub_sku_code(code, merchant) and code not in result:
            result.append(code)
    return result

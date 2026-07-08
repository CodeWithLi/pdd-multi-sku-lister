"""库存下架 — 测试用：飞书真实查询后覆盖指定编码可用数。"""

from __future__ import annotations

from typing import Any


def normalize_product_code(code: str) -> str:
    return str(code or "").strip().upper()


def parse_test_inventory_overrides(
    *,
    enabled: bool = False,
    overrides: dict[str, int] | None = None,
    text: str | None = None,
) -> dict[str, int]:
    """
    解析测试覆盖配置。

    text 每行格式：商品编码 或 商品编码,可用数（默认可用数 -1）
    """
    if not enabled:
        return {}
    result: dict[str, int] = {}
    if overrides:
        for code, qty in overrides.items():
            norm = normalize_product_code(code)
            if not norm:
                continue
            try:
                result[norm] = int(qty)
            except (TypeError, ValueError):
                result[norm] = -1
    if text:
        for raw_line in str(text).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.replace("，", ",").split(",") if p.strip()]
            if not parts:
                continue
            code = normalize_product_code(parts[0])
            if not code:
                continue
            qty = -1
            if len(parts) >= 2:
                try:
                    qty = int(float(parts[1]))
                except (TypeError, ValueError):
                    qty = -1
            result[code] = qty
    return result


def apply_test_inventory_overrides(
    inventory_map: dict[str, int],
    overrides: dict[str, int],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """
    在飞书真实返回的 inventory_map 上应用测试覆盖。

    返回 (新 map, 覆盖明细)。
    """
    if not overrides:
        return dict(inventory_map), []

    merged = dict(inventory_map)
    index = {normalize_product_code(k): k for k in merged.keys()}
    applied: list[dict[str, Any]] = []

    for code, override_qty in overrides.items():
        norm = normalize_product_code(code)
        if not norm:
            continue
        matched_key = index.get(norm)
        original_qty = merged.get(matched_key) if matched_key else None
        store_key = matched_key or code.strip()
        merged[store_key] = int(override_qty)
        if matched_key is None:
            index[norm] = store_key
        applied.append(
            {
                "code": code.strip(),
                "matched_key": store_key,
                "original_qty": original_qty,
                "override_qty": int(override_qty),
                "feishu_had_record": matched_key is not None,
            }
        )
    return merged, applied

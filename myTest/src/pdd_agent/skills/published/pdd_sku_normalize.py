"""Normalize PDD goods lookup SKU rows for campaign price validation."""

from __future__ import annotations

from typing import Any

from pdd_agent.skills.published.pdd_spec_format import enrich_sku_spec_fields


def split_spec_code(spec_code: str) -> tuple[str, str]:
    code = str(spec_code or "").strip().upper()
    if not code:
        return "", ""
    if "+" not in code:
        return code, ""
    left, right = code.split("+", 1)
    return left.strip(), right.strip()


def normalize_pdd_lookup_sku(raw: dict[str, Any]) -> dict[str, Any]:
    spec_code = str(raw.get("spec_code") or "").strip().upper()
    style_code, model_code = split_spec_code(spec_code)
    package = str(raw.get("package_name") or raw.get("model_name") or "").strip()
    style_name = str(raw.get("style_name") or raw.get("spec_dim1_value") or "").strip()

    base = {
        "style_name": style_name,
        "package_name": package,
        "model_name": package,
        "style_code": style_code,
        "model_code": model_code,
        "combo_folder": spec_code,
        "spec_code": spec_code,
        "group_price": str(raw.get("group_price") or "").strip(),
        "single_price": str(raw.get("single_price") or "").strip(),
    }
    spec_fields = enrich_sku_spec_fields(
        {**raw, **base},
        default_dim1_key=str(raw.get("spec_dim1_key") or "款式"),
        default_dim2_key=str(raw.get("spec_dim2_key") or "套餐"),
    )
    return {**base, **spec_fields}


def normalize_pdd_lookup_skus(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            out.append(normalize_pdd_lookup_sku(item))
    return out

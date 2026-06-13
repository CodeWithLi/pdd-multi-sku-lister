"""拼多多规格维度解析与组合（款式/尺寸 + 套餐，或单规格）。"""

from __future__ import annotations

import re
from typing import Any

# 第一维常见表头（商品编辑页、活动页）
SPEC_DIM1_KEYS = ("款式", "尺寸")
# 第二维常见表头
SPEC_DIM2_KEYS = ("套餐", "规格", "型号", "尺寸")
# 活动页第二维多为「套餐」，上架录入时常用「尺寸」
ACTIVITY_DIM2_KEY = "套餐"
LISTING_DIM2_KEY = "尺寸"

_DIM_PAIR_RE = re.compile(
    r"(款式|尺寸|套餐|规格|型号)\s*[：:]\s*([^；;]+)",
    re.IGNORECASE,
)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _strip_price_tail(text: str) -> str:
    return re.split(r"当前价", str(text or ""), maxsplit=1)[0].strip()


def build_spec_combined(
    dim1_key: str,
    dim1_value: str,
    dim2_key: str = "",
    dim2_value: str = "",
) -> str:
    """组合活动页常见格式：「款式: xxx；套餐: yyy」或单规格。"""
    dim1_key = str(dim1_key or "").strip()
    dim1_value = _collapse_ws(dim1_value)
    dim2_key = str(dim2_key or "").strip()
    dim2_value = _collapse_ws(dim2_value)
    if not dim1_value and dim2_value:
        dim1_key, dim1_value, dim2_key, dim2_value = dim2_key, dim2_value, "", ""
    if not dim1_value:
        return ""
    if dim2_key and dim2_value:
        return f"{dim1_key}: {dim1_value}；{dim2_key}: {dim2_value}"
    return f"{dim1_key}: {dim1_value}"


def parse_spec_text(spec_name: str) -> dict[str, Any]:
    """
    解析活动价确认页等处的规格文本。
    支持：款式/尺寸 + 套餐/规格/型号；单规格；旧式「款式 + 型号」。
    """
    text = _strip_price_tail(spec_name)
    pairs: list[tuple[str, str]] = []

    for match in _DIM_PAIR_RE.finditer(text):
        key = match.group(1).strip()
        value = _collapse_ws(match.group(2))
        value = re.sub(r"\(主图款式\)", "", value).strip()
        if value:
            pairs.append((key, value))

    dim1_key = ""
    dim1_value = ""
    dim2_key = ""
    dim2_value = ""

    if pairs:
        dim1_key, dim1_value = pairs[0]
        if len(pairs) >= 2:
            dim2_key, dim2_value = pairs[1]
    else:
        # 旧式：「款式: xxx；尺寸/规格/套餐: yyy」分段但未全部被正则捕获时回退
        legacy = _parse_legacy_spec_text(text)
        dim1_key = legacy.get("dim1_key") or ""
        dim1_value = legacy.get("dim1_value") or ""
        dim2_key = legacy.get("dim2_key") or ""
        dim2_value = legacy.get("dim2_value") or ""

    spec_count = 2 if dim2_value else (1 if dim1_value else 0)
    is_combo = spec_count >= 2
    if dim2_value and "单件装" in dim2_value and "+" not in dim2_value:
        is_combo = False
    if spec_count == 1 and dim1_value:
        dim1_value = re.sub(r"\s*-\s*[^-]+$", "", dim1_value).strip()

    spec_combined = build_spec_combined(dim1_key, dim1_value, dim2_key, dim2_value)

    return {
        "dim1_key": dim1_key,
        "dim1_value": dim1_value,
        "dim2_key": dim2_key,
        "dim2_value": dim2_value,
        "spec_count": spec_count,
        "spec_combined": spec_combined,
        # 兼容旧字段
        "style_text": dim1_value,
        "size_text": dim2_value,
        "is_combo": is_combo,
    }


def _parse_legacy_spec_text(text: str) -> dict[str, str]:
    style_text = ""
    size_text = ""
    dim1_key = "款式"
    dim2_key = ""

    size_parts = re.split(r"[；;]\s*尺寸[：:]\s*", text, maxsplit=1)
    if len(size_parts) == 1:
        size_parts = re.split(r"[；;]\s*规格[：:]\s*", text, maxsplit=1)
        if len(size_parts) == 2:
            dim2_key = "规格"
    if len(size_parts) == 1:
        size_parts = re.split(r"[；;]\s*套餐[：:]\s*", text, maxsplit=1)
        if len(size_parts) == 2:
            dim2_key = "套餐"
    if len(size_parts) == 2:
        style_part, size_text = size_parts[0].strip(), size_parts[1].strip()
    else:
        style_part = text
        if re.search(r"尺寸[：:]", text):
            dim1_key = "尺寸"

    style_text = re.sub(r"^(款式|尺寸|规格)[：:]\s*", "", style_part).strip()
    style_text = re.sub(r"\(主图款式\)", "", style_text).strip()
    size_text = re.sub(r"^(规格|套餐|尺寸|型号)[：:]\s*", "", size_text).strip()

    if not size_text and " + " in style_text:
        left, right = style_text.split(" + ", 1)
        style_text, size_text = left.strip(), right.strip()
        dim2_key = dim2_key or "套餐"
    elif not size_text:
        style_text = re.sub(r"\s*-\s*[^-]+$", "", style_text).strip()

    if size_text and not dim2_key:
        dim2_key = "套餐"

    return {
        "dim1_key": dim1_key,
        "dim1_value": _collapse_ws(style_text),
        "dim2_key": dim2_key,
        "dim2_value": _collapse_ws(size_text),
    }


def clean_spec_fragment(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^(款式|尺寸|规格|套餐|型号)[：:]\s*", "", value)
    value = re.sub(r"\(主图款式\)", "", value)
    return re.sub(r"\s+", "", value)


def listing_sku_spec_fields(
    *,
    style_name: str,
    model_name: str = "",
    listing_dim2_key: str = LISTING_DIM2_KEY,
) -> dict[str, Any]:
    """上架时写入 spec_metadata：记录录入维度名 + 活动页组合串。"""
    dim1_key = "款式"
    dim1_value = _collapse_ws(style_name)
    dim2_value = _collapse_ws(model_name)
    has_dim2 = bool(dim2_value)
    spec_count = 2 if has_dim2 else (1 if dim1_value else 0)

    activity_dim2_key = ACTIVITY_DIM2_KEY if has_dim2 else ""
    spec_combined = build_spec_combined(
        dim1_key, dim1_value, activity_dim2_key, dim2_value
    )
    spec_combined_listing = build_spec_combined(
        dim1_key, dim1_value, listing_dim2_key if has_dim2 else "", dim2_value
    )

    return {
        "spec_dim1_key": dim1_key,
        "spec_dim1_value": dim1_value,
        "spec_dim2_key": listing_dim2_key if has_dim2 else "",
        "spec_dim2_value": dim2_value if has_dim2 else "",
        "spec_count": spec_count,
        "spec_combined": spec_combined,
        "spec_combined_listing": spec_combined_listing,
    }


def enrich_sku_spec_fields(
    raw: dict[str, Any],
    *,
    default_dim1_key: str = "款式",
    default_dim2_key: str = ACTIVITY_DIM2_KEY,
) -> dict[str, Any]:
    """为反查/上架 SKU 补全维度键、组合串（保留 style_name / package_name）。"""
    dim1_key = str(raw.get("spec_dim1_key") or default_dim1_key).strip() or "款式"
    dim2_key = str(raw.get("spec_dim2_key") or "").strip()
    dim1_value = _collapse_ws(
        raw.get("spec_dim1_value") or raw.get("style_name") or ""
    )
    dim2_value = _collapse_ws(
        raw.get("spec_dim2_value")
        or raw.get("package_name")
        or raw.get("model_name")
        or ""
    )

    spec_count = raw.get("spec_count")
    if spec_count is None:
        spec_count = 2 if dim2_value else (1 if dim1_value else 0)
    else:
        spec_count = int(spec_count)

    if not dim2_key and int(spec_count) >= 2:
        dim2_key = default_dim2_key or ACTIVITY_DIM2_KEY
    if int(spec_count) < 2:
        dim2_key = ""
        dim2_value = ""

    spec_combined = str(raw.get("spec_combined") or "").strip()
    if not spec_combined:
        spec_combined = build_spec_combined(dim1_key, dim1_value, dim2_key, dim2_value)

    listing_combined = str(raw.get("spec_combined_listing") or "").strip()
    if not listing_combined and dim2_value:
        alt_dim2 = LISTING_DIM2_KEY if dim2_key == ACTIVITY_DIM2_KEY else dim2_key
        listing_combined = build_spec_combined(dim1_key, dim1_value, alt_dim2, dim2_value)
    elif not listing_combined:
        listing_combined = spec_combined

    return {
        "spec_dim1_key": dim1_key,
        "spec_dim1_value": dim1_value,
        "spec_dim2_key": dim2_key,
        "spec_dim2_value": dim2_value,
        "spec_count": spec_count,
        "spec_combined": spec_combined,
        "spec_combined_listing": listing_combined,
    }


def listing_unit_sku_metadata(sku: Any) -> dict[str, Any]:
    """上架 SKU → spec_metadata.skus 单项（含维度键与组合串）。"""
    spec_fields = listing_sku_spec_fields(
        style_name=getattr(sku, "style_name", "") or "",
        model_name=getattr(sku, "model_name", "") or "",
    )
    return {
        "style_code": getattr(sku, "style_code", "") or "",
        "style_name": getattr(sku, "style_name", "") or "",
        "model_code": getattr(sku, "model_code", "") or "",
        "model_name": getattr(sku, "model_name", "") or "",
        "combo_folder": getattr(sku, "combo_folder", "") or "",
        "preview_image": str(getattr(sku, "preview_image", "") or ""),
        "inventory": getattr(sku, "inventory", 0),
        "group_price": getattr(sku, "group_price", "") or "",
        "single_price": getattr(sku, "single_price", "") or "",
        **spec_fields,
    }

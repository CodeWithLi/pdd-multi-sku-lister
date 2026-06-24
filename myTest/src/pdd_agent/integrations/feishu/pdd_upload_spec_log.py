"""PDD 发布成功日志 — 按规格编码展开多行写入飞书。"""

from __future__ import annotations

import re
from typing import Any

from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.skills.listing.pdd_product_catalog import (
    get_pdd_product_catalog,
    lookup_catalog_spec,
)


def log_spec_sku_rows_enabled(cfg: FeishuConfig | None = None) -> bool:
    cfg = cfg or load_feishu_config()
    return bool(cfg.pdd_upload_log.log_spec_sku_rows_enabled)


def parse_spec_code_parts(spec_code: str) -> list[str]:
    text = str(spec_code or "").strip().upper()
    if not text:
        return []
    return [part.strip() for part in text.split("+") if part.strip()]


def _normalize_title_base(title: str, merchant_code: str = "") -> str:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    code = str(merchant_code or "").strip().upper()
    if code and text.upper().startswith(code):
        text = text[len(code) :].strip(" -—_")
    return text


def _sku_spec_code(sku: dict[str, Any]) -> str:
    for key in ("combo_folder", "spec_code", "style_code"):
        value = str(sku.get(key) or "").strip().upper()
        if value:
            return value
    return ""


def _sku_dimension_labels(sku: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in ("style_name", "model_name", "spec_combined_listing", "spec_combined"):
        value = str(sku.get(key) or "").strip()
        if value and value not in labels:
            labels.append(value)
    return labels


def resolve_spec_color_labels(
    spec_code: str,
    *,
    merchant_code: str = "",
    catalog: dict[str, Any] | None = None,
    sku: dict[str, Any] | None = None,
) -> str:
    """组合编码 → 飞书「颜色规格」拼接；缺数据时用上架时的款式/套餐名。"""
    cat = catalog if catalog is not None else get_pdd_product_catalog()
    labels: list[str] = []
    parent = str(merchant_code or "").strip().upper()
    spec_upper = str(spec_code or "").strip().upper()
    is_combo = "+" in spec_upper
    for part in parse_spec_code_parts(spec_code):
        if is_combo and parent and part.upper() == parent:
            continue
        spec = lookup_catalog_spec(part, cat)
        if spec:
            labels.append(str(spec).strip())
    if not labels and sku:
        labels.extend(_sku_dimension_labels(sku))
    if not labels:
        if parent and spec_upper == parent:
            spec = lookup_catalog_spec(parent, cat)
            if spec:
                labels.append(str(spec).strip())
    return " ".join(dict.fromkeys(item for item in labels if item))


def build_spec_upload_log_title(
    *,
    listing_title: str,
    merchant_code: str,
    combo_barcode: str = "",
    sku: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
) -> str:
    base = _normalize_title_base(listing_title, merchant_code)
    combo = str(combo_barcode or "").strip().upper()
    if not combo or combo == str(merchant_code or "").strip().upper():
        return base
    suffix = resolve_spec_color_labels(
        combo,
        merchant_code=merchant_code,
        catalog=catalog,
        sku=sku,
    )
    if suffix:
        return f"{base} {suffix}".strip()
    return base


def build_pdd_upload_spec_log_rows(
    *,
    merchant_code: str,
    listing_title: str,
    sku_rows: list[dict[str, Any]],
    catalog: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """生成飞书发布日志行：1 条商品摘要 + 每条规格编码 1 行。"""
    code = str(merchant_code or "").strip().upper()
    title_base = str(listing_title or "").strip()
    normalized_skus = [item for item in sku_rows if isinstance(item, dict)]
    rows: list[dict[str, Any]] = []

    summary_prices = _pick_prices_from_skus(normalized_skus, prefer_code=code)
    rows.append(
        {
            "merchant_code": code,
            "combo_barcode": "",
            "title": build_spec_upload_log_title(
                listing_title=title_base,
                merchant_code=code,
                combo_barcode="",
            ),
            "group_price": summary_prices.get("group_price", ""),
            "single_price": summary_prices.get("single_price", ""),
            "row_kind": "summary",
        }
    )

    seen_specs: set[str] = set()
    for sku in normalized_skus:
        spec_code = _sku_spec_code(sku)
        if not spec_code or spec_code in seen_specs:
            continue
        seen_specs.add(spec_code)
        if spec_code == code and "+" not in spec_code:
            continue
        rows.append(
            {
                "merchant_code": code,
                "combo_barcode": spec_code,
                "title": build_spec_upload_log_title(
                    listing_title=title_base,
                    merchant_code=code,
                    combo_barcode=spec_code,
                    sku=sku,
                    catalog=catalog,
                ),
                "group_price": str(sku.get("group_price") or "").strip(),
                "single_price": str(sku.get("single_price") or "").strip(),
                "row_kind": "spec",
            }
        )
    return rows


def _pick_prices_from_skus(skus: list[dict[str, Any]], *, prefer_code: str) -> dict[str, str]:
    target = str(prefer_code or "").strip().upper()
    for sku in skus:
        spec = _sku_spec_code(sku)
        if spec == target:
            return {
                "group_price": str(sku.get("group_price") or "").strip(),
                "single_price": str(sku.get("single_price") or "").strip(),
            }
    if skus:
        first = skus[0]
        return {
            "group_price": str(first.get("group_price") or "").strip(),
            "single_price": str(first.get("single_price") or "").strip(),
        }
    return {"group_price": "", "single_price": ""}


def sku_rows_from_spec_metadata(spec_metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(spec_metadata, dict):
        return []
    skus = spec_metadata.get("skus")
    if not isinstance(skus, list):
        return []
    return [item for item in skus if isinstance(item, dict)]

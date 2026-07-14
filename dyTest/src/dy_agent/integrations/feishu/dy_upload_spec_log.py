"""DY 发布成功日志 — 按规格编码展开多行写入飞书（对齐 PDD）。"""

from __future__ import annotations

import re
from typing import Any

from dy_agent.integrations.feishu.config import FeishuConfig, load_feishu_config


def log_spec_sku_rows_enabled(cfg: FeishuConfig | None = None) -> bool:
    cfg = cfg or load_feishu_config()
    return bool(cfg.dy_upload_log.log_spec_sku_rows_enabled)


def listing_unit_sku_metadata(sku: Any) -> dict[str, Any]:
    """上架 SKU → 飞书规格行元数据。"""
    return {
        "style_code": str(getattr(sku, "style_code", "") or "").strip(),
        "style_name": str(getattr(sku, "style_name", "") or "").strip(),
        "model_code": str(getattr(sku, "model_code", "") or "").strip(),
        "model_name": str(getattr(sku, "model_name", "") or "").strip(),
        "combo_folder": str(getattr(sku, "combo_folder", "") or "").strip(),
        "price": str(getattr(sku, "price", "") or "").strip(),
        "spec_code": str(getattr(sku, "combo_folder", "") or getattr(sku, "style_code", "") or "").strip(),
    }


def _sku_spec_code(sku: dict[str, Any]) -> str:
    for key in ("combo_folder", "spec_code", "style_code"):
        value = str(sku.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalize_title_base(title: str, merchant_code: str = "") -> str:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    code = str(merchant_code or "").strip()
    if code and text.upper().startswith(code.upper()):
        text = text[len(code) :].strip(" -—_")
    return text


def _sku_dimension_labels(sku: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in ("style_name", "model_name"):
        value = str(sku.get(key) or "").strip()
        if value and value not in labels:
            labels.append(value)
    return labels


def build_spec_upload_log_title(
    *,
    listing_title: str,
    merchant_code: str,
    combo_barcode: str = "",
    sku: dict[str, Any] | None = None,
) -> str:
    base = _normalize_title_base(listing_title, merchant_code)
    combo = str(combo_barcode or "").strip()
    merchant = str(merchant_code or "").strip()
    if not combo or combo == merchant:
        return base
    labels = _sku_dimension_labels(sku or {})
    if labels:
        return f"{base} {' '.join(labels)}".strip()
    return base


def _pick_price_from_skus(skus: list[dict[str, Any]], *, prefer_code: str) -> str:
    target = str(prefer_code or "").strip()
    for sku in skus:
        if _sku_spec_code(sku) == target:
            return str(sku.get("price") or "").strip()
    if skus:
        return str(skus[0].get("price") or "").strip()
    return ""


def build_dy_upload_spec_log_rows(
    *,
    merchant_code: str,
    listing_title: str,
    sku_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """生成飞书 DY 发布日志行：1 条商品摘要 + 每条规格编码 1 行。"""
    code = str(merchant_code or "").strip()
    title_base = str(listing_title or "").strip()
    normalized_skus = [item for item in sku_rows if isinstance(item, dict)]
    rows: list[dict[str, Any]] = []

    rows.append(
        {
            "merchant_code": code,
            "combo_barcode": "",
            "title": build_spec_upload_log_title(
                listing_title=title_base,
                merchant_code=code,
                combo_barcode="",
            ),
            "price": _pick_price_from_skus(normalized_skus, prefer_code=code),
            "row_kind": "summary",
        }
    )

    seen_specs: set[str] = set()
    for sku in normalized_skus:
        spec_code = _sku_spec_code(sku)
        if not spec_code or spec_code in seen_specs:
            continue
        seen_specs.add(spec_code)
        # 单款且与商品编码相同：已由摘要行覆盖，跳过
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
                ),
                "price": str(sku.get("price") or "").strip(),
                "row_kind": "spec",
            }
        )
    return rows

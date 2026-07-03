"""
语义槽位对齐：兄弟款按 enrich 后的尺寸名（笔袋+挂件、笔袋+套尺…）匹配槽位，
而非 YKL 子编码。供「规格校验填表」使用；旧「槽位对齐」仍走 YKL 签名。
"""

from __future__ import annotations

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.pdd_product_catalog import (
    BUNDLE_MODEL_CODE,
    catalog_codes_match,
)
from pdd_agent.skills.listing.slot_alignment import SlotAlignmentResult, apply_slot_alignment


def normalize_semantic_size_label(name: str) -> str:
    """消歧后缀不参与槽位签名，如 笔袋+挂件(公仔) → 笔袋+挂件。"""
    text = str(name or "").strip()
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    return text


def semantic_slot_signature(sku: SkuCombo) -> str:
    """
    槽位签名：单款 solo；组合款用商品表推断的尺寸语义名。
    兄弟款 YKL 不同但同为「笔袋+挂件」时签名相同。
    """
    style = str(sku.style_code or "").strip().upper()
    model_code = str(sku.model_code or "").strip().upper()
    if not style:
        return f"raw:{sku.combo_folder}"
    if catalog_codes_match(model_code, style) or model_code == style:
        return "solo"
    if str(model_code or "").strip() == BUNDLE_MODEL_CODE:
        label = normalize_semantic_size_label(str(sku.model_name or ""))
        if label:
            return f"bundle:{label}"
        return f"bundle:{sku.combo_folder}"
    label = normalize_semantic_size_label(str(sku.model_name or ""))
    if label:
        return f"size:{label}"
    return f"raw:{sku.combo_folder}"


def apply_semantic_slot_alignment(
    unit: ListingUnit,
    *,
    account_id: str = "",
) -> SlotAlignmentResult:
    """按尺寸语义名对齐兄弟款槽位（规格校验填表专用）。"""
    return apply_slot_alignment(
        unit,
        account_id=account_id,
        signature_for_sku=lambda sku, _code: semantic_slot_signature(sku),
        log_tag="语义槽位对齐",
    )

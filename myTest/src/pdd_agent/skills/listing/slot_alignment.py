"""
槽位对齐（试验功能）

主款按预览图顺序定 N 个尺寸槽位；兄弟款跟槽位索引共用尺寸名，避免尺寸名并集膨胀。
关闭开关时不调用本模块，现有流程不变。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.catalog import _preview_sort_key


@dataclass
class SlotAlignmentResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    reference_style: str = ""
    slot_count: int = 0
    slot_labels: list[str] = field(default_factory=list)


def _skus_for_style(unit: ListingUnit, style_code: str) -> list[SkuCombo]:
    target = style_code.strip().upper()
    return [sku for sku in unit.skus if sku.style_code.strip().upper() == target]


def _sort_skus_by_slot(skus: list[SkuCombo], style_code: str) -> list[SkuCombo]:
    return sorted(
        skus,
        key=lambda sku: _preview_sort_key(sku.preview_image, style_code),
    )


def _pick_reference_style(unit: ListingUnit) -> str:
    codes = sorted({sku.style_code.strip().upper() for sku in unit.skus if sku.style_code})
    if not codes:
        return (unit.product_code or "").strip().upper()
    product = (unit.product_code or "").strip().upper()
    if product in codes:
        return product
    return codes[0]


def validate_slot_structure(unit: ListingUnit) -> list[str]:
    """检查各兄弟款预览图数量是否一致（未改 SKU 前）。"""
    style_codes = sorted({sku.style_code.strip().upper() for sku in unit.skus if sku.style_code})
    if len(style_codes) < 2:
        return []

    counts: dict[str, int] = {}
    for code in style_codes:
        counts[code] = len(_skus_for_style(unit, code))
    values = list(counts.values())
    if len(set(values)) == 1:
        return []

    detail = "，".join(f"{code}={counts[code]}张" for code in style_codes)
    return [
        f"[{unit.listing_label}] 槽位对齐失败：兄弟款预览图数量不一致（{detail}）"
    ]


def apply_slot_alignment(unit: ListingUnit, *, account_id: str = "") -> SlotAlignmentResult:
    """
    主款槽位名覆盖兄弟款同索引 SKU 的 model_name，并重写 unit.model_codes。
    调用前应先完成常规 enrich_listing_unit_specs。
    """
    prefix = f"[{account_id}] " if account_id else ""
    errors = validate_slot_structure(unit)
    if errors:
        return SlotAlignmentResult(ok=False, errors=errors)

    style_codes = sorted({sku.style_code.strip().upper() for sku in unit.skus if sku.style_code})
    if not style_codes:
        return SlotAlignmentResult(ok=False, errors=[f"[{unit.listing_label}] 无有效款式编码"])

    reference = _pick_reference_style(unit)
    groups = {code: _sort_skus_by_slot(_skus_for_style(unit, code), code) for code in style_codes}
    ref_skus = groups.get(reference) or []
    if not ref_skus:
        return SlotAlignmentResult(
            ok=False,
            errors=[f"[{unit.listing_label}] 主款 {reference} 无 SKU"],
        )

    slot_labels = [sku.model_name for sku in ref_skus]
    slot_count = len(slot_labels)

    for code, skus in groups.items():
        if len(skus) != slot_count:
            return SlotAlignmentResult(
                ok=False,
                errors=[
                    f"[{unit.listing_label}] 槽位对齐失败：{code} 有 {len(skus)} 张图，"
                    f"主款 {reference} 有 {slot_count} 张"
                ],
            )

    for code, skus in groups.items():
        if code == reference:
            continue
        for idx, sku in enumerate(skus):
            old = sku.model_name
            sku.model_name = slot_labels[idx]
            if prefix and old != sku.model_name:
                print(
                    f"{prefix}[{unit.listing_label}] 槽位对齐 {code}#{idx + 1}："
                    f"{sku.combo_folder} {old} → {sku.model_name}",
                    flush=True,
                )

    unit.model_codes = list(slot_labels)
    expected_skus = slot_count * len(style_codes)
    if len(unit.skus) != expected_skus:
        return SlotAlignmentResult(
            ok=False,
            errors=[
                f"[{unit.listing_label}] 槽位对齐后 SKU 数异常："
                f"期望 {expected_skus}，实际 {len(unit.skus)}"
            ],
        )

    print(
        f"{prefix}[{unit.listing_label}] 槽位对齐完成：主款={reference}，"
        f"{slot_count} 槽 × {len(style_codes)} 款 = {expected_skus} SKU",
        flush=True,
    )
    return SlotAlignmentResult(
        ok=True,
        reference_style=reference,
        slot_count=slot_count,
        slot_labels=slot_labels,
    )

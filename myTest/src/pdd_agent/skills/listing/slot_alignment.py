"""
槽位对齐（试验功能）

主款按预览图顺序定 N 个尺寸槽位；兄弟款跟槽位索引共用尺寸名，避免尺寸名并集膨胀。
关闭开关时不调用本模块，现有流程不变。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pdd_agent.domain.listing_errors import ListingErrors
from pdd_agent.domain.models import ListingUnit, SkuCombo
from pdd_agent.skills.listing.catalog import (
    _collect_flat_preview_images,
    _filter_preview_images_for_code_dir,
    _preview_sort_key,
    combo_slot_signature,
)


def _sibling_style_dir(unit: ListingUnit, style_code: str) -> Path | None:
    """同套图下某款式编码目录（如 .../第一套图/BD716A）。"""
    root = unit.root
    image_set = str(unit.image_set or "").strip()
    if image_set and root.parent.name == image_set:
        set_dir = root.parent
    elif root.parent.is_dir():
        set_dir = root.parent
    else:
        return None
    candidate = set_dir / style_code
    return candidate if candidate.is_dir() else None


def count_style_preview_files(unit: ListingUnit, style_code: str) -> int:
    """该款式目录下非数字命名的规格预览图张数（与素材检查「全部图片」里 SKU 图一致）。"""
    style_dir = _sibling_style_dir(unit, style_code)
    if style_dir is None:
        return 0
    previews = _filter_preview_images_for_code_dir(
        style_dir,
        _collect_flat_preview_images(style_dir),
    )
    return len(previews)


def _missing_sku_labels(unit: ListingUnit, style_code: str) -> list[str]:
    """目录里有规格图但未纳入 SKU 的子编码（多为商品表缺行）。"""
    from pdd_agent.skills.listing.catalog import _parse_combo_code

    style_dir = _sibling_style_dir(unit, style_code)
    if style_dir is None:
        return []
    previews = _filter_preview_images_for_code_dir(
        style_dir,
        _collect_flat_preview_images(style_dir),
    )
    sku_folders = {sku.combo_folder for sku in _skus_for_style(unit, style_code)}
    labels: list[str] = []
    for preview in previews:
        if preview.stem in sku_folders:
            continue
        parsed = _parse_combo_code(preview.stem, style_code)
        if parsed:
            _, model = parsed
            norm_style = style_code.strip().upper()
            if model.strip().upper() == norm_style:
                labels.append("单款图")
            else:
                labels.append(model)
        elif "+" in preview.stem:
            labels.append(preview.stem.split("+", 1)[1])
        else:
            labels.append(preview.stem)
    return labels


def format_slot_mismatch_message(unit: ListingUnit) -> str:
    """短小精悍的兄弟款规格不齐说明，供飞书失败表与前端展示。"""
    style_codes = sorted({sku.style_code.strip().upper() for sku in unit.skus if sku.style_code})
    if len(style_codes) < 2:
        return ""

    display_code: dict[str, str] = {}
    for sku in unit.skus:
        key = sku.style_code.strip().upper()
        display_code.setdefault(key, sku.style_code.strip())

    sku_counts = {code: len(_skus_for_style(unit, code)) for code in style_codes}
    preview_counts = {
        code: count_style_preview_files(unit, display_code.get(code, code))
        for code in style_codes
    }
    target = max(sku_counts.values())
    if len(set(sku_counts.values())) == 1:
        return ""

    count_parts: list[str] = []
    for code in style_codes:
        label = display_code.get(code, code)
        parsed = sku_counts[code]
        previews = preview_counts[code]
        missing = _missing_sku_labels(unit, label) if parsed < target else []
        if missing:
            count_parts.append(f"{label}缺{'/'.join(missing)}")
        elif previews != parsed:
            count_parts.append(f"{label}解析{parsed}个/图{previews}张")
        else:
            count_parts.append(f"{label}{parsed}个")

    max_count = max(sku_counts.values())
    min_count = min(sku_counts.values())
    heavy = [display_code.get(c, c) for c in style_codes if sku_counts[c] == max_count]
    light = [display_code.get(c, c) for c in style_codes if sku_counts[c] == min_count]
    detail = "，".join(count_parts)
    if max_count > min_count and heavy and light:
        detail += f"（{'/'.join(heavy)}多{max_count - min_count}个）"

    return ListingErrors.format_slot_mismatch(detail, target)


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
    """检查各兄弟款 SKU 数量是否一致（未改 SKU 前）。"""
    msg = format_slot_mismatch_message(unit)
    return [msg] if msg else []


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
        return SlotAlignmentResult(ok=False, errors=[ListingErrors.Msg.SLOT_NO_STYLE.format(label=unit.listing_label)])

    reference = _pick_reference_style(unit)
    groups = {code: _sort_skus_by_slot(_skus_for_style(unit, code), code) for code in style_codes}
    ref_skus = groups.get(reference) or []
    if not ref_skus:
        return SlotAlignmentResult(
            ok=False,
            errors=[ListingErrors.Msg.SLOT_REF_NO_SKU.format(label=unit.listing_label, reference=reference)],
        )

    ref_signatures = [combo_slot_signature(sku.combo_folder, reference) for sku in ref_skus]
    slot_labels = [sku.model_name for sku in ref_skus]
    sig_to_label = dict(zip(ref_signatures, slot_labels))
    slot_count = len(slot_labels)

    for code, skus in groups.items():
        if len(skus) != slot_count:
            msg = format_slot_mismatch_message(unit)
            return SlotAlignmentResult(
                ok=False,
                errors=[
                    msg
                    if msg
                    else ListingErrors.Msg.SLOT_MISMATCH_FALLBACK.format(
                        code=code, reference=reference, count=slot_count
                    )
                ],
            )

    for code, skus in groups.items():
        if code == reference:
            continue
        used_labels: set[str] = set()
        unmatched: list[SkuCombo] = []
        for sku in skus:
            sig = combo_slot_signature(sku.combo_folder, code)
            target_label = sig_to_label.get(sig)
            if target_label and target_label not in used_labels:
                old = sku.model_name
                sku.model_name = target_label
                used_labels.add(target_label)
                if prefix and old != sku.model_name:
                    print(
                        f"{prefix}[{unit.listing_label}] 槽位对齐 {code} [{sig}]："
                        f"{sku.combo_folder} {old} → {sku.model_name}",
                        flush=True,
                    )
            else:
                unmatched.append(sku)

        remaining_labels = [label for label in slot_labels if label not in used_labels]
        unmatched_sorted = _sort_skus_by_slot(unmatched, code)
        if len(unmatched_sorted) > len(remaining_labels):
            return SlotAlignmentResult(
                ok=False,
                errors=[
                    ListingErrors.Msg.SLOT_MISMATCH_FALLBACK.format(
                        code=code, reference=reference, count=slot_count
                    )
                ],
            )
        for sku, target_label in zip(unmatched_sorted, remaining_labels):
            old = sku.model_name
            sku.model_name = target_label
            used_labels.add(target_label)
            if prefix and old != sku.model_name:
                sig = combo_slot_signature(sku.combo_folder, code)
                print(
                    f"{prefix}[{unit.listing_label}] 槽位对齐 {code} [{sig}]："
                    f"{sku.combo_folder} {old} → {sku.model_name}",
                    flush=True,
                )

    unit.model_codes = list(slot_labels)
    expected_skus = slot_count * len(style_codes)
    if len(unit.skus) != expected_skus:
        return SlotAlignmentResult(
            ok=False,
            errors=[
                ListingErrors.Msg.SLOT_COUNT_ABNORMAL.format(
                    label=unit.listing_label,
                    expected=expected_skus,
                    actual=len(unit.skus),
                )
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

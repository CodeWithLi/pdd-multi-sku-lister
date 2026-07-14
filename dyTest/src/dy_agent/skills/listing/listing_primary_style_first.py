"""将本套图主上架编码对应款式置于规格「款式」维度第一位。"""

from __future__ import annotations

from dataclasses import dataclass

from dy_agent.domain.models import ListingUnit, SkuCombo


@dataclass(frozen=True)
class PrimaryStyleFirstResult:
    applied: bool
    product_code: str = ""
    primary_style_code: str = ""
    primary_style_name: str = ""
    displaced_first_code: str = ""
    style_order: tuple[str, ...] = ()


def catalog_codes_match(left: str, right: str) -> bool:
    a = str(left or "").strip().casefold()
    b = str(right or "").strip().casefold()
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _resolve_primary_style_code(unit: ListingUnit) -> str:
    product = str(unit.product_code or "").strip()
    if not product:
        return ""
    for code in unit.style_codes or []:
        if catalog_codes_match(code, product):
            return str(code).strip()
    for sku in unit.skus or []:
        sc = str(getattr(sku, "style_code", "") or "").strip()
        if sc and catalog_codes_match(sc, product):
            return sc
    return product


def _style_name_for_code(unit: ListingUnit, style_code: str) -> str:
    target = str(style_code or "").strip()
    if not target:
        return ""
    for sku in unit.skus or []:
        if catalog_codes_match(getattr(sku, "style_code", ""), target):
            return str(getattr(sku, "style_name", "") or "").strip()
    return ""


def _reorder_style_codes(codes: list[str], primary: str) -> tuple[list[str], bool]:
    if not codes or not primary:
        return codes, False
    if catalog_codes_match(codes[0], primary):
        return codes, False
    idx = next(
        (i for i, code in enumerate(codes) if catalog_codes_match(code, primary)),
        None,
    )
    if idx is None or idx == 0:
        return codes, False
    reordered = [codes[idx], *codes[:idx], *codes[idx + 1 :]]
    return reordered, True


def _reorder_skus_by_style_codes(skus: list[SkuCombo], style_codes: list[str]) -> list[SkuCombo]:
    if not skus or not style_codes:
        return list(skus or [])
    grouped: dict[str, list[SkuCombo]] = {}
    for sku in skus:
        key = str(getattr(sku, "style_code", "") or "").strip()
        grouped.setdefault(key, []).append(sku)
    ordered: list[SkuCombo] = []
    seen: set[str] = set()
    for code in style_codes:
        bucket = grouped.get(code)
        if not bucket:
            for gkey, items in grouped.items():
                if gkey in seen:
                    continue
                if catalog_codes_match(gkey, code):
                    bucket = items
                    seen.add(gkey)
                    break
        if not bucket:
            continue
        seen.add(code)
        ordered.extend(bucket)
    for key, items in grouped.items():
        if any(catalog_codes_match(key, used) for used in seen):
            continue
        if key in seen:
            continue
        ordered.extend(items)
    return ordered or list(skus)


def reorder_unit_primary_style_first(
    unit: ListingUnit,
    *,
    account_id: str = "",
) -> PrimaryStyleFirstResult:
    product = str(unit.product_code or "").strip()
    if not product or not unit.skus:
        return PrimaryStyleFirstResult(applied=False, product_code=product)

    codes = list(unit.style_codes or [])
    if not codes:
        codes = list(dict.fromkeys(str(s.style_code or "").strip() for s in unit.skus if s.style_code))

    primary = _resolve_primary_style_code(unit)
    previous_first = str(codes[0] or "") if codes else ""
    new_codes, moved = _reorder_style_codes(codes, primary)
    if not moved:
        return PrimaryStyleFirstResult(
            applied=False,
            product_code=product,
            primary_style_code=primary,
            primary_style_name=_style_name_for_code(unit, primary),
            displaced_first_code=previous_first,
            style_order=tuple(codes),
        )

    unit.style_codes = new_codes
    unit.skus = _reorder_skus_by_style_codes(list(unit.skus), new_codes)

    primary_name = _style_name_for_code(unit, primary)
    prefix = f"[{account_id}] " if account_id else ""
    print(
        f"{prefix}[{unit.listing_label}] 主款款式优先：{primary}"
        f"{f'（{primary_name}）' if primary_name else ''} "
        f"移至款式列第 1 位（原首位 {previous_first}）",
        flush=True,
    )
    return PrimaryStyleFirstResult(
        applied=True,
        product_code=product,
        primary_style_code=primary,
        primary_style_name=primary_name,
        displaced_first_code=previous_first,
        style_order=tuple(new_codes),
    )


def apply_primary_style_first_to_unit(
    unit: ListingUnit,
    *,
    account_id: str = "",
    enabled: bool = True,
) -> PrimaryStyleFirstResult | None:
    if not enabled:
        return None
    return reorder_unit_primary_style_first(unit, account_id=account_id)

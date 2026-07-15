"""撞名尺寸后缀简写：``笔袋+挂件(公仔)`` → ``笔袋+公仔``。

由 ``paren_size_as_product_type`` 开关启用。现有规格识别 / 消歧流程不变，
仅在规格名定稿后、填页面之前做一次改名。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pdd_agent.domain.models import ListingUnit
from pdd_agent.skills.listing.spec_labels import refresh_unit_spec_code_lists

# 消歧附加的简单类型后缀，如 笔袋+挂件(公仔)；不含 AI 区分词 公仔-鲨鱼
_PAREN_TYPE_RE = re.compile(r"^(?P<base>.+)\((?P<ptype>[^()\-/]+)\)$")


@dataclass(frozen=True)
class ParenSizeRewriteChange:
    style_code: str
    model_code: str
    combo_folder: str
    before: str
    after: str


@dataclass(frozen=True)
class ParenSizeRewriteResult:
    applied: bool
    changes: tuple[ParenSizeRewriteChange, ...] = ()


def rewrite_paren_disambiguation_label(label: str, *, sibling_bases: set[str]) -> str | None:
    """
    若 ``label`` 为 ``主类+子类(商品类型)``，且同组存在无括号的 ``主类+子类``，
    则改写为 ``主类+商品类型``（例：笔袋+挂件(公仔) → 笔袋+公仔）。
    不满足条件时返回 None。
    """
    text = str(label or "").strip()
    if not text:
        return None
    match = _PAREN_TYPE_RE.match(text)
    if not match:
        return None
    base = str(match.group("base") or "").strip()
    ptype = str(match.group("ptype") or "").strip()
    if not base or not ptype or "+" not in base:
        return None
    if base not in sibling_bases:
        return None
    mother = base.rsplit("+", 1)[0].strip()
    if not mother:
        return None
    rewritten = f"{mother}+{ptype}"
    if rewritten == text or rewritten == base:
        return None
    return rewritten


def apply_paren_size_as_product_type(
    unit: ListingUnit,
    *,
    account_id: str = "",
) -> ParenSizeRewriteResult:
    """
    扫描 unit.skus：同款式下若同时存在 ``笔袋+挂件`` 与 ``笔袋+挂件(公仔)``，
    将后者改为 ``笔袋+公仔``，并刷新 model_codes。
    """
    if not unit.skus:
        return ParenSizeRewriteResult(applied=False)

    by_style: dict[str, list] = {}
    for sku in unit.skus:
        key = str(getattr(sku, "style_code", "") or "").strip() or "_"
        by_style.setdefault(key, []).append(sku)

    changes: list[ParenSizeRewriteChange] = []
    prefix = f"[{account_id}] " if account_id else ""

    for style_code, group in by_style.items():
        names = [str(getattr(sku, "model_name", "") or "").strip() for sku in group]
        sibling_bases = {n for n in names if n and "(" not in n}
        used_after = {n for n in names if n}

        for sku in group:
            before = str(getattr(sku, "model_name", "") or "").strip()
            after = rewrite_paren_disambiguation_label(before, sibling_bases=sibling_bases)
            if not after:
                continue
            # 同款式已有同名尺寸则跳过，避免制造撞名
            if after in used_after:
                continue
            sku.model_name = after
            used_after.add(after)
            used_after.discard(before)
            change = ParenSizeRewriteChange(
                style_code=style_code,
                model_code=str(getattr(sku, "model_code", "") or "").strip(),
                combo_folder=str(getattr(sku, "combo_folder", "") or "").strip(),
                before=before,
                after=after,
            )
            changes.append(change)
            print(
                f"{prefix}[{unit.listing_label}] 尺寸简写："
                f"{change.model_code or change.combo_folder} {before} → {after}",
                flush=True,
            )

    if not changes:
        return ParenSizeRewriteResult(applied=False)

    refresh_unit_spec_code_lists(unit)
    return ParenSizeRewriteResult(applied=True, changes=tuple(changes))


def apply_paren_size_as_product_type_to_unit(
    unit: ListingUnit,
    *,
    account_id: str = "",
    enabled: bool = True,
) -> ParenSizeRewriteResult | None:
    """开关封装：未启用时返回 None。"""
    if not enabled:
        return None
    return apply_paren_size_as_product_type(unit, account_id=account_id)

"""失败日志循环上架：飞书商品编码 → MinIO 套图 selector 解析（仅循环场景）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pdd_agent.integrations.feishu.listing_feishu_catalog import codes_match, normalize_listing_code
from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config, minio_configured
from pdd_agent.integrations.minio.index import MinioSetIndexRecord, list_minio_set_records_for_family
from pdd_agent.skills.listing.catalog import _image_set_sort_key

_ALNUM_PREFIX = re.compile(r"^([A-Za-z0-9]+)")


@dataclass(frozen=True)
class CycleRelistListingResolveResult:
    ok: bool
    merchant_code: str = ""
    family_code: str = ""
    image_set: str = ""
    product_folder: str = ""
    selector: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "merchant_code": self.merchant_code,
            "family_code": self.family_code,
            "image_set": self.image_set,
            "product_folder": self.product_folder,
            "selector": self.selector,
            "error": self.error,
        }


def extract_cycle_relist_family_code(merchant_code: str) -> str:
    """
    从飞书商品编码截取母款号：去掉末尾一个英文字母 A-Z。

    BD685B -> BD685
    BD023B毛绒小猫笔袋 -> BD023
    """
    text = str(merchant_code or "").strip()
    match = _ALNUM_PREFIX.match(text)
    if not match:
        return ""
    prefix = match.group(1).upper()
    if len(prefix) > 1 and prefix[-1].isalpha():
        return prefix[:-1]
    return prefix


def _match_product_folder(merchant_code: str, folder_names: list[str]) -> str:
    target = str(merchant_code or "").strip()
    if not target:
        return ""
    normalized_target = normalize_listing_code(target)
    for folder in folder_names:
        name = str(folder or "").strip()
        if not name:
            continue
        if normalize_listing_code(name) == normalized_target:
            return name
        if codes_match(target, name):
            return name
    return ""


def _records_for_family(family_code: str, config: MinioConfig | None = None) -> list[MinioSetIndexRecord]:
    family = str(family_code or "").strip().upper()
    if not family:
        return []

    cfg = config or load_minio_config()
    records = list_minio_set_records_for_family(family, cfg)

    if not records:
        if cfg.enabled:
            from pdd_agent.integrations.minio.catalog import list_minio_listing_targets

            targets = list_minio_listing_targets(cfg)
        else:
            from pdd_agent.integrations.minio.config import minio_cache_root
            from pdd_agent.skills.listing.catalog import list_listing_targets_from_root

            targets = list_listing_targets_from_root(minio_cache_root(cfg))
        for target in targets:
            if str(target.family_code or "").strip().upper() != family:
                continue
            records.append(
                MinioSetIndexRecord(
                    selector=str(target.selector or f"{target.family_code}/{target.image_set}"),
                    family_code=str(target.family_code or ""),
                    image_set=str(target.image_set or ""),
                    object_prefix=f"{target.family_code}/{target.image_set}/",
                    product_codes=tuple(str(code) for code in (target.product_codes or []) if str(code).strip()),
                )
            )

    records.sort(key=lambda item: _image_set_sort_key(item.image_set))
    return records


def resolve_cycle_relist_listing_selector(
    merchant_code: str,
    *,
    config: MinioConfig | None = None,
) -> CycleRelistListingResolveResult:
    """
    循环上架专用：按母款号在 MinIO 中依次查套图，按商品全称匹配文件夹。

    命中后返回三级 selector：母编码/套图/商品文件夹。
    """
    raw = str(merchant_code or "").strip()
    if not raw:
        return CycleRelistListingResolveResult(ok=False, merchant_code=raw, error="飞书商品编码为空")

    cfg = config or load_minio_config()
    if cfg.enabled and not minio_configured(cfg):
        return CycleRelistListingResolveResult(
            ok=False,
            merchant_code=raw,
            error="MinIO 未配置，循环上架无法解析套图",
        )

    family_code = extract_cycle_relist_family_code(raw)
    if not family_code:
        return CycleRelistListingResolveResult(
            ok=False,
            merchant_code=raw,
            error=f"无法从商品编码截取母款号：{raw}",
        )

    records = _records_for_family(family_code, cfg)
    if not records:
        return CycleRelistListingResolveResult(
            ok=False,
            merchant_code=raw,
            family_code=family_code,
            error=f"MinIO 未找到母款号目录：{family_code}",
        )

    for record in records:
        matched = _match_product_folder(raw, list(record.product_codes))
        if not matched:
            continue
        selector = f"{record.family_code}/{record.image_set}/{matched}"
        return CycleRelistListingResolveResult(
            ok=True,
            merchant_code=raw,
            family_code=record.family_code,
            image_set=record.image_set,
            product_folder=matched,
            selector=selector,
        )

    if len(records) == 1:
        only_set = records[0].image_set
        return CycleRelistListingResolveResult(
            ok=False,
            merchant_code=raw,
            family_code=family_code,
            image_set=only_set,
            error=(
                f"母款号 {family_code} 仅有一套图（{only_set}），"
                f"未找到商品文件夹：{raw}"
            ),
        )

    checked = "、".join(record.image_set for record in records)
    return CycleRelistListingResolveResult(
        ok=False,
        merchant_code=raw,
        family_code=family_code,
        error=(
            f"母款号 {family_code} 已查询全部套图（{checked}），"
            f"未找到商品文件夹：{raw}"
        ),
    )


def resolve_cycle_relist_listing_selectors(
    merchant_codes: list[str],
    *,
    config: MinioConfig | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """批量解析循环上架商品编码，返回 selector 列表与解析明细。"""
    selectors: list[str] = []
    details: list[dict[str, Any]] = []
    for raw in merchant_codes:
        code = str(raw or "").strip()
        if not code:
            continue
        result = resolve_cycle_relist_listing_selector(code, config=config)
        details.append(result.to_dict())
        if not result.ok:
            raise ValueError(result.error or f"循环上架套图解析失败：{code}")
        if result.selector not in selectors:
            selectors.append(result.selector)
    if not selectors:
        raise ValueError("无有效商品编码")
    return selectors, details

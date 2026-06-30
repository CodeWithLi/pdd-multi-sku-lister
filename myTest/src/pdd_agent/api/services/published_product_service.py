"""已发布商品：手动录入等服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from pdd_agent.api.services.catalog_service import get_product_detail
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.repositories import (
    _published_mapping_id,
    get_published_products_by_pdd_product_ids,
    upsert_published_product,
)
from pdd_agent.db.session import is_database_available
from pdd_agent.skills.listing.catalog import parse_all_listings
from pdd_agent.skills.published.pdd_spec_format import listing_unit_sku_metadata


def _normalize_pdd_product_id(value: str) -> str:
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits or text


def _spec_metadata_from_catalog(product_code: str, image_set: str) -> dict[str, Any] | None:
    settings = load_yaml_settings()
    units = parse_all_listings(product_code, settings, include_excel_missing_previews=True)
    if not units:
        return None
    target_set = str(image_set or "").strip()
    unit = None
    if target_set:
        for item in units:
            if str(item.image_set or "").strip() == target_set:
                unit = item
                break
    if unit is None:
        unit = units[0]
    return {
        "family_code": unit.family_code,
        "product_code": unit.product_code,
        "image_set": unit.image_set,
        "listing_label": unit.listing_label,
        "merchant_code": unit.merchant_code,
        "root": str(unit.root),
        "carousel_images": [str(path) for path in unit.carousel_images],
        "detail_images": [str(path) for path in unit.detail_images],
        "material_image": str(unit.material_image) if unit.material_image else "",
        "style_codes": list(unit.style_codes),
        "model_codes": list(unit.model_codes),
        "skus": [listing_unit_sku_metadata(sku) for sku in unit.skus],
        "source": "manual_catalog_import",
    }


def create_manual_published_product(
    *,
    account_id: str,
    pdd_product_id: str,
    product_code: str,
    listing_label: str,
    family_code: str = "",
    image_set: str = "",
    merchant_code: str = "",
    status: str = "on_sale",
    note: str = "",
    import_catalog_skus: bool = True,
) -> dict[str, Any]:
    """手动录入拼多多已有商品到 published_products。"""
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL published products unavailable")

    account_id = str(account_id or "").strip()
    product_code = str(product_code or "").strip().upper()
    listing_label = str(listing_label or "").strip()
    family_code = str(family_code or "").strip().upper()
    image_set = str(image_set or "").strip()
    merchant_code = str(merchant_code or "").strip().upper()
    status = str(status or "on_sale").strip() or "on_sale"
    note = str(note or "").strip()
    pdd_product_id = _normalize_pdd_product_id(pdd_product_id)

    if not account_id:
        raise HTTPException(status_code=422, detail="请选择店铺 account_id")
    if not pdd_product_id or not pdd_product_id.isdigit():
        raise HTTPException(status_code=422, detail="拼多多商品 ID 必须是纯数字")
    if not product_code:
        raise HTTPException(status_code=422, detail="请填写商品编码 product_code")
    if not listing_label:
        raise HTTPException(status_code=422, detail="请填写显示名称 listing_label")
    if status not in {"on_sale", "delisted"}:
        raise HTTPException(status_code=422, detail="状态只能是 on_sale 或 delisted")
    if not get_account_or_none(account_id):
        raise HTTPException(status_code=422, detail=f"未知店铺: {account_id}")

    mapping_id = _published_mapping_id(account_id, product_code, image_set)
    existing_by_pdd = get_published_products_by_pdd_product_ids(
        account_id=account_id,
        pdd_product_ids=[pdd_product_id],
    )
    for row in existing_by_pdd:
        if row.mapping_id != mapping_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"该店铺下商品 ID {pdd_product_id} 已绑定到 "
                    f"{row.product_code}/{row.image_set or '默认'}（mapping={row.mapping_id}）"
                ),
            )

    catalog_detail = get_product_detail(product_code)
    catalog_meta: dict[str, Any] | None = None
    catalog_hints: list[str] = []
    if import_catalog_skus:
        catalog_meta = _spec_metadata_from_catalog(product_code, image_set)
        if catalog_meta:
            if not family_code:
                family_code = str(catalog_meta.get("family_code") or "").strip().upper()
            if not image_set:
                image_set = str(catalog_meta.get("image_set") or "").strip()
            if not merchant_code:
                merchant_code = str(catalog_meta.get("merchant_code") or product_code).strip().upper()
            sku_count = len(catalog_meta.get("skus") or [])
            catalog_hints.append(f"已从素材目录导入 {sku_count} 条 SKU，用于活动价格校验")
        elif catalog_detail:
            catalog_hints.append("素材目录有该编码，但未解析到 SKU；请检查套图名称或规格文件夹")
        else:
            catalog_hints.append(
                "素材目录未找到该编码，仅保存基础映射；活动价格校验/限时限量购可能缺少 SKU 数据"
            )
    else:
        catalog_hints.append(
            "未使用本地素材；可正常用于活动选品报名（如 21365）。"
            "若后续要做 20981 价格校验或限时限量购，请改选「本地也有素材目录」并补全编码"
        )

    spec_metadata: dict[str, Any] = dict(catalog_meta or {})
    spec_metadata.update(
        {
            "source": "manual",
            "manual_note": note,
            "catalog_imported": bool(catalog_meta),
        }
    )

    row = upsert_published_product(
        account_id=account_id,
        source_run_id="manual",
        product_code=product_code,
        family_code=family_code,
        image_set=image_set,
        listing_label=listing_label,
        merchant_code=merchant_code or product_code,
        pdd_product_id=pdd_product_id,
        spec_metadata=spec_metadata,
        status=status,
        published_at=datetime.now(),
    )
    if not row:
        raise HTTPException(status_code=500, detail="写入 published_products 失败")

    return {
        "published": row,
        "catalog_hints": catalog_hints,
        "created": True,
    }

"""已上架素材文件夹记录（普通上架与整合链路共用）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.db.repositories import (
    backfill_listed_folders_from_published_products,
    build_folder_selector,
    delete_listed_asset_folder_for_product,
    get_listed_product_codes_for_set,
    get_queue_task_by_run_id,
    list_listed_asset_folders,
    prune_listed_folders_against_catalog,
    upsert_listed_asset_folder,
)


def resolve_listing_source_meta(run_id: str) -> tuple[str, str]:
    """根据队列任务 payload 判断来源：listing 或 integrated_pipeline。"""
    task = get_queue_task_by_run_id(run_id)
    if not task:
        return "listing", ""
    pipeline_id = str((task.payload or {}).get("pipeline_id") or "").strip()
    if pipeline_id:
        return "integrated_pipeline", pipeline_id
    return "listing", ""


def record_listed_folder_from_item(run_id: str, account_id: str, item: dict[str, Any]) -> None:
    """上架成功后记录素材文件夹（与 published_products 同步触发）。"""
    if not isinstance(item, dict):
        return
    if str(item.get("status") or "") not in {"success", "listed"}:
        return
    pdd_product_id = str(item.get("pdd_product_id") or "").strip()
    product_code = str(item.get("product_code") or "").strip()
    family_code = str(item.get("family_code") or "").strip()
    image_set = str(item.get("image_set") or "").strip()
    listing_label = str(item.get("listing_label") or "").strip()
    if not account_id or not product_code:
        return

    spec_metadata = item.get("spec_metadata") if isinstance(item.get("spec_metadata"), dict) else {}
    if not family_code:
        family_code = str(spec_metadata.get("family_code") or "").strip()
    if not image_set:
        image_set = str(spec_metadata.get("image_set") or "").strip()
    if not listing_label:
        listing_label = str(spec_metadata.get("listing_label") or "").strip() or (
            f"{product_code}/{image_set}" if image_set else product_code
        )

    folder_selector = build_folder_selector(
        family_code=family_code,
        image_set=image_set,
        product_code=product_code,
    )
    if not folder_selector:
        return

    asset_path = str(spec_metadata.get("root") or "").strip()
    source_kind, pipeline_id = resolve_listing_source_meta(run_id)

    upsert_listed_asset_folder(
        account_id=account_id,
        folder_selector=folder_selector,
        family_code=family_code,
        image_set=image_set,
        product_code=product_code,
        listing_label=listing_label,
        asset_path=asset_path,
        source_run_id=run_id,
        source_kind=source_kind,
        pipeline_id=pipeline_id,
        pdd_product_id=pdd_product_id,
        listed_at=datetime.now(),
    )


def listed_folder_rows_for_account(account_id: str) -> list:
    account_id = str(account_id or "").strip()
    if not account_id:
        return []
    return list_listed_asset_folders(account_id=account_id, limit=5000)


def listed_product_codes_by_set(account_id: str) -> dict[str, list[str]]:
    """返回 {套图selector: [已上架商品编码]}，与当前素材目录实时对齐。"""
    from pdd_agent.core.config import load_yaml_settings
    from pdd_agent.db.repositories import build_catalog_set_index

    settings = load_yaml_settings()
    catalog_index = build_catalog_set_index(settings)
    account_id = str(account_id or "").strip()
    if account_id:
        prune_listed_folders_against_catalog(account_id=account_id, catalog_index=catalog_index)
    return get_listed_product_codes_for_set(account_id, catalog_index=catalog_index)


def sync_listed_folders_with_catalog(*, account_id: str = "") -> int:
    """素材目录变更后同步：移除目录中已不存在的上架记录。"""
    from pdd_agent.core.config import load_yaml_settings
    from pdd_agent.db.repositories import build_catalog_set_index

    settings = load_yaml_settings()
    catalog_index = build_catalog_set_index(settings)
    return prune_listed_folders_against_catalog(account_id=account_id, catalog_index=catalog_index)


def ensure_listed_folder_backfill() -> int:
    created = backfill_listed_folders_from_published_products()
    return created


def remove_listed_folder_for_published_product(
    *,
    account_id: str,
    product_code: str,
    family_code: str = "",
    image_set: str = "",
) -> bool:
    """已发布商品下架/删除时，同步移除已上架文件夹记录。"""
    return delete_listed_asset_folder_for_product(
        account_id=account_id,
        product_code=product_code,
        family_code=family_code,
        image_set=image_set,
    )

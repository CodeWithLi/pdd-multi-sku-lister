"""飞书 / 上架相关进程内内存缓存清理。"""

from __future__ import annotations

from typing import Any

from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)


def clear_feishu_data_caches(*, include_listing_snapshot: bool = True) -> dict[str, Any]:
    """清空当前 worker 进程内的飞书商品表、比价定价等内存缓存。

    多 worker 部署时每个进程各有一份缓存，需在各进程各调一次（或重启全部 worker）。
    """
    cleared: list[str] = []
    errors: list[str] = []

    def _run(label: str, fn) -> None:
        try:
            fn()
            cleared.append(label)
        except Exception as exc:
            logger.exception("clear feishu cache failed: %s", label)
            errors.append(f"{label}: {exc}")

    from pdd_agent.integrations.feishu.pdd_price_compare_sync import clear_price_compare_caches
    from pdd_agent.integrations.feishu.pdd_product_catalog_sync import clear_pdd_product_catalog_cache

    _run("price_compare", clear_price_compare_caches)
    _run("product_catalog", clear_pdd_product_catalog_cache)

    try:
        from pdd_agent.skills.listing.pdd_product_catalog import get_pdd_product_catalog

        get_pdd_product_catalog.cache_clear()
        cleared.append("product_catalog_lru")
    except Exception as exc:
        logger.exception("clear product catalog lru failed")
        errors.append(f"product_catalog_lru: {exc}")

    try:
        from pdd_agent.integrations.feishu.bitable import clear_table_field_caches

        clear_table_field_caches()
        cleared.append("bitable_field_lookup")
    except Exception as exc:
        logger.exception("clear bitable field caches failed")
        errors.append(f"bitable_field_lookup: {exc}")

    if include_listing_snapshot:
        try:
            from pdd_agent.integrations.feishu.listing_feishu_snapshot import clear_listing_feishu_snapshot

            clear_listing_feishu_snapshot()
            cleared.append("listing_feishu_snapshot")
        except Exception as exc:
            logger.exception("clear listing feishu snapshot failed")
            errors.append(f"listing_feishu_snapshot: {exc}")

    result = {
        "success": not errors,
        "cleared": cleared,
        "errors": errors,
        "message": (
            "已清空当前进程飞书数据缓存"
            if not errors
            else "部分缓存清理失败，请查看 errors"
        ),
        "worker_scope": "current_process_only",
    }
    logger.info("feishu data caches cleared cleared=%s errors=%s", cleared, errors)
    return result
